#!/usr/bin/env python
# Copyright 2015 Fortinet, Inc.
#
# All Rights Reserved
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

###################################################################
#
# fortiosapi.py aims at simplifying the configuration and
# integration of Fortgate configuration using the restapi
#
# A Python module to abstract configuration using FortiOS REST API
#
###################################################################

import copy
import json

# Set default logging handler to avoid "No handler found" warnings.
import logging
import subprocess
import time
from collections import OrderedDict

import netmiko
import requests
import urllib.parse

from .exceptions import InvalidLicense, NotLogged

try:  # Python 2.7+
    from logging import NullHandler
except ImportError:

    class NullHandler(logging.Handler):
        def emit(self, record):
            pass


# Disable warnings about certificates.
# from requests.packages.urllib3.exceptions import InsecureRequestWarning

# requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
# may need to move to specifying the ca or use Verify=false
# verify="/etc/ssl/certs/" on Debian to use the system CAs
logging.getLogger(__name__).addHandler(NullHandler())
# create logger
LOG = logging.getLogger("fortiosapi")


class FortiOSAPI:
    """
    Global class / example for FortiOSAPI
    """

    def __init__(self):
        self.host = None
        self._https = True
        self._logged = False
        self._fortiversion = "Version is set when logged"
        # reference the fortinet version of the targeted product.
        self._session = requests.session()  # use single session
        # persistant and same for all
        self._session.verify = True
        # (can be changed to) self._session.verify = '/etc/ssl/certs/' or False
        self.timeout = 120
        self.cert = None
        self._apitoken = None
        self._license = None
        self.url_prefix = None

    @staticmethod
    def logging(response):
        try:
            LOG.debug(f"response content type : {response.headers["content-type"]}")
            LOG.debug(
                f"Request : {response.request.method} on url : {response.request.url}  "
            )
            LOG.debug(
                f"Response : http code {response.status_code}  reason : {response.reason}  "
            )
            LOG.debug(f"raw response:  {response.content} ")
        except:
            LOG.warning("method errors in request when global")

    @staticmethod
    def debug(status):
        """
        Set the debug to on to have all the debug information from the library
        You should add logging.getLogger(\'fortiosapi\') to your log handler

        :param status: on to set the log level to DEBUG
        :return:
            None
        """

        if status == "on":
            LOG.setLevel(logging.DEBUG)

    def formatresponse(self, res, vdom=None):
        LOG.debug("formating response")
        self.logging(res)
        # Generic way to format the return from FortiAPI
        # If vdom is global the resp is a dict of resp (even 1)
        # 1 per vdom we check only the first one here (might need a more
        # complex check)
        if self._license == "Invalid":
            LOG.debug("License invalid detected")
            raise Exception("invalid license")

        try:
            if vdom == "global":
                resp = json.loads(res.content.decode("utf-8"))[0]
                resp["vdom"] = "global"
            else:
                LOG.debug(f"content res: {res.content}")
                resp = json.loads(res.content.decode("utf-8"))
            return resp
        except:
            # that means res.content does not exist (error in general)
            # in that case return raw result TODO fix that with a loop in case of global
            LOG.warning(
                "in formatresponse res.content does not exist, should not occur"
            )
            return res

    def check_session(self):
        """
        Helper fonction to check if the session on the FortiOSAPI object is valid
        :return:
            True or raise NotLogged or InvalidLicense
        """
        if not self._logged:
            raise NotLogged()
        if self._license == "Invalid":
            raise InvalidLicense()

    def https(self, status):
        """
        Allow to use http or https (default).
        HTTP is necessary to use the API on unlicensed/trial Fortigates

        :param status: 'on' to use https to connect to API, anything else will http
        :return:
        """
        if status == "on":
            self._https = True
        if status == "off":
            self._https = False
        LOG.debug(f"https mode is {self._https}")

    def update_cookie(self):
        # Retrieve server csrf and update session's headers
        LOG.debug(f"cookies are  : {self._session.cookies} ")
        for cookie in self._session.cookies:
            if cookie.name == "ccsrftoken" or cookie.name.startswith("ccsrftoken_"):
                csrftoken = cookie.value[1:-1]  # token stored as a list
                LOG.debug(f"csrftoken before update  : {csrftoken} ")
                self._session.headers.update({"X-CSRFTOKEN": csrftoken})
                LOG.debug(f"csrftoken after update  : {csrftoken} ")
        LOG.debug(f"New session header is: {self._session.headers}")

    def login(
        self,
        host,
        username,
        password,
        verify=True,
        cert=None,
        timeout=12,
        vdom="global",
    ):
        """
        Initialize the connection to the API with the related credentials.
        Further calls on the object will reuse the session initiated here.

        :param host: ip or name (fqdn) can include a port like 10.40.40.40:8443
        :param username: name of API user
        :param password: password of API user
        :param verify: True verify validity of the Fortigate API ssl certificate, False ignore
        :param cert: client certificate to authenticate
        :param timeout: global timeout on the url session
        :param vdom: default is root, can use global or name of the vdom to use
        :return:
        """
        self.host = host
        LOG.debug(f"self._https is {self._https}")
        if not self._https:
            self.url_prefix = "http://" + self.host
        else:
            self.url_prefix = "https://" + self.host

        url = self.url_prefix + "/logincheck"
        if not self._session:
            self._session = requests.session()
            # may happen if logout is called
        self._session.verify = verify

        if cert != None:
            self._session.cert = cert
        # set the default at 12 see request doc for details http://docs.python-requests.org/en/master/user/advanced/
        self.timeout = timeout

        res = self._session.post(
            url,
            data="username="
            + urllib.parse.quote(username)
            + "&secretkey="
            + urllib.parse.quote(password)
            + "&ajax=1",
            timeout=self.timeout,
        )
        self.logging(res)
        # Ajax=1 documented in 5.6 API ref but available on 5.4
        LOG.debug(f"logincheck res : {res.content}")
        if res.content.decode("ascii")[0] == "1":
            # Update session's csrftoken
            self.update_cookie()
            self._logged = True
            LOG.debug(f"host is {host}")
            param = "{ vdom = " + vdom + " }"
            resp_lic = self.monitor("license", "status", parameters=param)
            LOG.debug(f"response system/status : {resp_lic}")

            if type(resp_lic) != dict:
                resp_lic = resp_lic.json()

            try:
                self._fortiversion = resp_lic["version"]
                return True
            except KeyError:
                if resp_lic["status"] == "success":
                    self._logged = True
                    return True
                else:
                    self._logged = False
                    raise NotLogged
        else:
            self._logged = False
            raise NotLogged

    def tokenlogin(
        self, host, apitoken, verify=True, cert=None, timeout=12, vdom="global"
    ):
        """
        Initialize the connection to the API with the related apitoken.
        Further calls on the object will reuse the session initiated here.
        Using apitoken method then login/passwd will be disabled

        :param host: ip or name (fqdn) can include a port like 10.40.40.40:8443
        :param apitoken: Token obtained on the Fortigate or forced see official doc
        :param verify: True verify validity of the Fortigate API ssl certificate, False ignore
        :param cert: client certificate to authenticate
        :param timeout: global timeout on the url session
        :param vdom: default is root, can use global or name of the vdom to use
        :return:
        """
        self.host = host
        if not self._session:
            self._session = requests.session()
            # may happen at start or if logout is called
        self._session.headers.update({"Authorization": "Bearer " + apitoken})
        self._logged = True
        LOG.debug(f"self._https is {self._https}")
        if not self._https:
            self.url_prefix = "http://" + self.host
        else:
            self.url_prefix = "https://" + self.host

        self._session.verify = verify

        if cert != None:
            self._session.cert = cert
        # set the default at 12 see request doc for details http://docs.python-requests.org/en/master/user/advanced/
        self.timeout = timeout

        LOG.debug(f"host is {host}")
        resp_lic = self.get("system", "status", vdom=vdom)
        LOG.debug(f"response system/status : {resp_lic}")
        try:
            self._fortiversion = resp_lic["version"]
        except TypeError:
            raise NotLogged
        return True

    def get_version(self):
        """

        :return: the version of the fortigate used
        """
        self.check_session()
        return self._fortiversion

    def get_mkeyname(self, path, name, vdom=None):
        """

        :param path:
        :param name:
        :param vdom:
        :return:
        """
        # retreive the table mkey from schema
        schema = self.schema(path, name, vdom=vdom)
        try:
            keyname = schema["mkey"]
        except KeyError:
            LOG.warning("there is no mkey for %s/%s", path, name)
            return False
        return keyname

    def get_mkey(self, path, name, data, vdom=None):
        """

        :param path:
        :param name:
        :param data:
        :param vdom:
        :return:
        """
        # retreive the table mkey from schema

        keyname = self.get_mkeyname(path, name, vdom)
        if not keyname:
            LOG.warning("there is no mkey for %s/%s", path, name)
            return None
        else:
            try:
                mkey = data[keyname]
            except KeyError:
                LOG.warning("mkey not set in the data")
                return None
            return mkey

    def logout(self):
        """

        :return:
        """
        url = self.url_prefix + "/logout"
        res = self._session.post(url, timeout=self.timeout)
        self._session.close()
        self._session.cookies.clear()
        self._logged = False
        # set license to Valid by default to ensure rechecked at login
        self._license = "Valid"
        self.logging(res)

    def cmdb_url(self, path, name, vdom=None, mkey=None):

        self.check_session()
        # return builded URL
        url_postfix = "/api/v2/cmdb/" + path + "/" + name
        if mkey:
            url_postfix = url_postfix + "/" + urllib.parse.quote(str(mkey), safe="")
        if vdom:
            LOG.debug("vdom is: %s", vdom)
            if vdom == "global":
                url_postfix += "?global=1"
            else:
                url_postfix += "?vdom=" + vdom
        url = self.url_prefix + url_postfix
        LOG.debug("urlbuild is %s with crsf: %s", url, self._session.headers)
        return url

    def mon_url(self, path, name, vdom=None, mkey=None):
        self.check_session()
        # return builded URL
        url_postfix = "/api/v2/monitor/" + path + "/" + name
        if mkey:
            url_postfix = url_postfix + "/" + urllib.parse.quote(str(mkey), safe="")
        if vdom:
            LOG.debug("vdom is: %s", vdom)
            if vdom == "global":
                url_postfix += "?global=1"
            else:
                url_postfix += "?vdom=" + vdom

        url = self.url_prefix + url_postfix
        return url

    def download(self, path, name, vdom=None, mkey=None, parameters=None):
        """
        Use the download call on the monitoring part of the API.
        Can get the config, logs etc..

        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/cmdb/<path>/<name>
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add parameters understood by the API call in json. Must set \"destination\": \"file\" and scope
        :return:
            The file is part of the returned json
        """
        url = self.mon_url(path, name, vdom=vdom, mkey=mkey)
        res = self._session.get(url, params=parameters, timeout=self.timeout)
        LOG.debug("in DOWNLOAD function")
        LOG.debug(" result download : %s", res.content)
        return res

    def upload(
        self, path, name, vdom=None, mkey=None, parameters=None, data=None, files=None
    ):
        """
        Upload a file (refer to the monitoring part), used for license, config, certificates etc.. uploads.

        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/cmdb/<path>/<name>
        :param data: json containing the param/values of the object to be set
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add on parameters understood by the API call can be \"&select=\" for example
        :param files: the file to be uploaded
        :return:
            A formatted json with the last response from the API
        """
        # TODO should be file not files
        # TODO add a test
        url = self.mon_url(path, name, vdom=vdom, mkey=mkey)
        res = self._session.post(
            url, params=parameters, data=data, files=files, timeout=self.timeout
        )
        LOG.debug("in UPLOAD function")
        return res

    def get(self, path, name, vdom=None, mkey=None, parameters=None):
        """
        Execute a GET on the cmdb (i.e. configuration part) of the Fortios API

        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/cmdb/<path>/<name>
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add on parameters understood by the API call can be \"&select=\" for example
        :return:
            A formatted json with the last response from the API, values are in return['results']

        """
        url = self.cmdb_url(path, name, vdom, mkey=mkey)
        LOG.debug("Calling GET ( %s, %s)", url, parameters)
        res = self._session.get(url, params=parameters, timeout=self.timeout)
        LOG.debug("in GET function")
        return self.formatresponse(res, vdom=vdom)

    def monitor(self, path, name, vdom=None, mkey=None, parameters=None):
        """
        Execute a GET on the montioring part of the Fortios API
        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/monitor/<path>/<name>
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add on parameters understood by the API call can be \"&select=\" for example
        :return:
            A formatted json with the last response from the API, values are in return['results']

        """
        url = self.mon_url(path, name, vdom, mkey)
        LOG.debug("in monitor url is %s", url)
        res = self._session.get(url, params=parameters, timeout=self.timeout)
        LOG.debug("in MONITOR function")
        return self.formatresponse(res, vdom=vdom)

    def schema(self, path, name, vdom=None):
        # vdom or global is managed in cmdb_url
        if vdom == None:
            url = self.cmdb_url(path, name) + "?action=schema"
        else:
            url = self.cmdb_url(path, name, vdom=vdom) + "&action=schema"

        res = self._session.get(url, timeout=self.timeout)
        if res.status_code == 200:
            if vdom == "global":
                return json.loads(res.content.decode("utf-8"))[0]["results"]
            else:
                return json.loads(res.content.decode("utf-8"))["results"]
        else:
            return json.loads(res.content.decode("utf-8"))

    def get_name_path_dict(self, vdom=None):
        # return builded URL
        url_postfix = "/api/v2/cmdb/"
        if vdom != None:
            url_postfix += "?vdom=" + vdom + "&action=schema"
        else:
            url_postfix += "?action=schema"

        url = self.url_prefix + url_postfix
        cmdbschema = self._session.get(url, timeout=self.timeout)
        self.logging(cmdbschema)
        j = json.loads(cmdbschema.content.decode("utf-8"))["results"]
        dict = []
        for keys in j:
            if "__tree__" not in keys["path"]:
                dict.append(keys["path"] + " " + keys["name"])
        return dict

    def post(self, path, name, data, vdom=None, mkey=None, parameters=None):
        """
         Execute a REST POST on the API. It will fail if the targeted object already exist.
         When post to the upper name/path the mkey is in the data.
         So we can ensure the data set is correctly filled in case mkey is passed.

        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/cmdb/<path>/<name>
        :param data: json containing the param/values of the object to be set
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add on parameters understood by the API call can be \"&select=\" for example
        :return:
            A formatted json with the last response from the API
        """
        LOG.debug("in POST function")
        if mkey:
            mkeyname = self.get_mkeyname(path, name, vdom)
            LOG.debug("in post calculated mkeyname : %s mkey: %s ", mkeyname, mkey)
            # if mkey is forced on the function call then we change it in the data
            # even if inconsistent data/mkey is passed
            data[mkeyname] = mkey
        # post with mkey will return a 404 as the next level is not there yet
        # we pushed mkey in data if needed.
        url = self.cmdb_url(path, name, vdom, mkey=None)
        LOG.debug("POST sent data : %s", json.dumps(data))
        res = self._session.post(
            url, params=parameters, data=json.dumps(data), timeout=self.timeout
        )
        LOG.debug("POST raw results: %s", res)
        return self.formatresponse(res, vdom=vdom)

    def execute(self, path, name, data, vdom=None, mkey=None, parameters=None):
        """
        Execute is an action done on a running fortigate
        it is actually doing a post to the monitor part of the API
        we choose this name for clarity

        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/monitor/<path>/<name>
        :param data: json containing the param/values of the object to be set
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add on parameters understood by the API call can be \"&select=\" for example
        :return:
            A formatted json with the last response from the API

        """
        LOG.debug("in EXEC function")

        url = self.mon_url(path, name, vdom, mkey=mkey)
        LOG.debug("EXEC sent data : %s", json.dumps(data))
        res = self._session.post(
            url, params=parameters, data=json.dumps(data), timeout=self.timeout
        )
        LOG.debug("EXEC raw results: %s", res)
        return self.formatresponse(res, vdom=vdom)

    def put(self, path, name, vdom=None, mkey=None, parameters=None, data=None):
        """
        Execute a REST PUT on the specified object with parameters in the data field as
        a json formatted field

        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/cmdb/<path>/<name>
        :param data: json containing the param/values of the object to be set
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add on parameters understood by the API call can be \"&select=\" for example
        :return:
            A formatted json with the last response from the API
        """
        if not mkey:
            mkey = self.get_mkey(path, name, data, vdom=vdom)
        url = self.cmdb_url(path, name, vdom, mkey)
        res = self._session.put(
            url, params=parameters, data=json.dumps(data), timeout=self.timeout
        )
        LOG.debug("in PUT function")
        return self.formatresponse(res, vdom=vdom)

    def move(
        self,
        path,
        name,
        vdom=None,
        mkey=None,
        where=None,
        reference_key=None,
        parameters={},
    ):
        # TODO add a test in the tOx suit
        """
        Move an object in a cmdb table (firewall/policies for example).
        Usefull for reordering too
        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/cmdb/<path>/<name>
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add on parameters understood by the API call can be \"&select=\" for example
        :param where: the destination mkey in the table
        :param reference_key: the origin mkey in the table
        :return:
            A formatted json with the last response from the API
        """
        url = self.cmdb_url(path, name, vdom, mkey)
        parameters["action"] = "move"
        parameters[where] = str(reference_key)
        res = self._session.put(url, params=parameters, timeout=self.timeout)
        LOG.debug("in MOVE function")
        return self.formatresponse(res, vdom=vdom)

    def delete(self, path, name, vdom=None, mkey=None, parameters=None, data=None):
        """
        Delete a pointed object in the cmdb.

        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/cmdb/<path>/<name>
        :param data: json containing the param/values of the object to be set
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add on parameters understood by the API call can be \"&select=\" for example
        :return:
            A formatted json with the last response from the API
        """
        # Need to find the type of the mkey to avoid error when integer assume
        # the other types will be ok.
        if not mkey:
            mkey = self.get_mkey(path, name, data, vdom=vdom)
        url = self.cmdb_url(path, name, vdom, mkey)
        res = self._session.delete(
            url, params=parameters, data=json.dumps(data), timeout=self.timeout
        )

        LOG.debug("in DELETE function")
        return self.formatresponse(res, vdom=vdom)

    # Set will try to put if err code is 424 will try post (424 is ressource exists)
    # may add a force option to delete and redo if troubles.
    def set(self, path, name, data, mkey=None, vdom=None, parameters=None):
        """
        Fortios API definition is at https://fndn.fortinet.net
        Function targeting config management. You pass the data of the part of cmdb you want to be set and the function
        will try POST and PUT to ensure your modification go through.

        :param path: first part of the Fortios API URL like
        :param name: https://myfgt:8040/api/v2/cmdb/<path>/<name>
        :param data: json containing the param/values of the object to be set
        :param mkey: when the cmdb object have a subtable mkey represent the subobject.
                     It is optionnal at creation the code will find the mkey name for you.
        :param vdom: the vdom on which you want to apply config or global for global settings
        :param parameters: Add on parameters understood by the API call can be \"&select=\" for example
        :return:
            A formatted json with the last response from the API
        """
        # post with mkey will return a 404 as the next level is not there yet
        if not mkey:
            mkey = self.get_mkey(path, name, data, vdom=vdom)
        url = self.cmdb_url(path, name, vdom, mkey)
        res = self._session.put(
            url, params=parameters, data=json.dumps(data), timeout=self.timeout
        )
        LOG.debug("in SET function after PUT")
        r = self.formatresponse(res, vdom=vdom)

        if (
            r["http_status"] == 404
            or r["http_status"] == 405
            or r["http_status"] == 500
        ):
            LOG.warning(
                "Try to put on %s  failed doing a put to force parameters\
                change consider delete if still fails ",
                res.request.url,
            )
            res = self.post(path, name, data, vdom, mkey)
            LOG.debug("in SET function after POST result %s", res)
            return self.formatresponse(res, vdom=vdom)
        else:
            return r

    @staticmethod
    def ssh(cmds, host, user, password=None, port=22):
        """
        Send a command or a set of commands via ssh to the fortigate

        Better to use Netmiko for this

        :param cmds: string or list of commands with the Fortigate config cli
        :param host: ip/hostname of the fortigate interface
        :param user/password: fortigate admin user and password
        :param port: port 22 if not set or a port on which fortigate listen for ssh commands.
        :return:
            The output of the console commands and raise exception if failed
        """

        device = {
            "host": host,
            "username": user,
            "password": password,
            "port": port,
            "device_type": "fortinet",
        }

        client = netmiko.ConnectHandler(**device)
        LOG.debug(f"ssh login to  {host}:{port} ")
        # commands is a string or a list
        try:
            if type(cmds) == list:
                output = client.send_config_set(cmds)

            else:
                output = client.send_command(cmds)

            client.disconnect()  # @TODO re-use connections
        except:
            LOG.debug("exec_command failed")
            raise subprocess.CalledProcessError(returncode=0, cmd=cmds, output=output)
        LOG.debug(f"ssh cmd {cmds} | out: {output} ")

        return output

    def license(self, vdom="root"):
        """
        license check and update:
         - GET /api/v2/monitor/license/status
         - If pending (exec update-now) with FortiGuard if invalid
           POST api/v2/monitor/system/fortiguard/update and do the GET again
          Convinient when Fortigate starts and license validity takes time.

        :param vdom: root by default, can be global to do a global check
        :return:
            True if license is valid at the end of the process
        """
        resp = self.monitor("license", "status", vdom=vdom)
        if resp["status"] == "success":
            LOG.debug(f"response monitor license status: {resp}")
            return resp
        # TODO check the return message for Warning or even Invalid (yet)
        else:
            # if license not valid we try to update and check again
            postresp = self.execute("system", "fortiguard/update", None, vdom=vdom)
            LOG.debug("Return EXECUTE fortiguard %s:", postresp)
            if postresp["status"] == "success":
                time.sleep(17)
                resp2 = self.monitor("license", "status", vdom=vdom)
                LOG.debug("after update response monitor license status: %s", resp2)
                return resp2

    def setoverlayconfig(self, yamltree, vdom=None):
        """
        take a yaml tree with
        name:
            path:
                mkey:
        structure and recursively set the values.
        create a copy to only keep the leaf as node (table firewall rules etc
        Split the tree in 2 yaml objects and iterates)
        Update the higher level, up to tables as those config parameters may influence which param are allowed
        in the level 3 table
        :param yamltree: a yaml formatted string of the differents part of CMDB to be changed
        :param vdom: (optionnal) default is root, can use vdom=global to swtich to global settings.
        :return:

        """

        yamltreel3 = copy.deepcopy(yamltree)
        LOG.debug(f"initial yamltreel3 is {yamltreel3} ")
        for name in yamltree.copy():
            for path in yamltree[name]:
                for k in yamltree[name][path].copy():
                    node = yamltree[name][path][k]
                    if isinstance(node, dict):
                        # if the node is a structure remove from yamltree keep in yamltreel3
                        LOG.debug(f"Delete yamltree k: {k} node: {node} ")
                        del yamltree[name][path][k]
                        LOG.debug(f"during DEL yamltreel3 is {yamltreel3} ")
                    else:
                        # Should then be a string only so remove from yamltreel3
                        del yamltreel3[name][path]
        # yamltree and yamltreel3 are now different
        LOG.debug(f"after yamltree is {yamltree} ")
        LOG.debug(f"after yamltreel3 is {yamltreel3} ")
        restree = False
        # Set the standard value on top of nodes first (example if setting firewall mode
        # it must be done before pushing a rule l3)
        # Set the standard value on top of nodes first (example if setting firewall mode it must be done before pushing a rule l3)
        for name in yamltree:
            for path in yamltree[name]:
                LOG.debug(
                    "iterate set in yamltree @ name: %s path %s value %s",
                    name,
                    path,
                    yamltree[name][path],
                )
                if yamltree[name][path]:
                    res = self.set(name, path, data=yamltree[name][path], vdom=vdom)
                    if res["status"] == "success":
                        restree = True
                    else:
                        restree = False
                        break

        for name in yamltreel3:
            for path in yamltreel3[name]:
                for k in yamltreel3[name][path].copy():
                    node = yamltreel3[name][path][k]
                    LOG.debug(
                        f"iterate set in yamltreel3 @ node: {k} value {yamltreel3[name][path][k]} "
                    )
                    res = self.set(name, path, mkey=k, data=node, vdom=vdom)
                    if res["status"] == "success":
                        restree = True
                    else:
                        restree = False
                        break

        # TODO   Must defined a coherent returned value out
        return restree
