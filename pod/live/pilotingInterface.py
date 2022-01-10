import json
from abc import ABC

import requests
from django.http import JsonResponse

from .models import Broadcaster
from django.conf import settings

BROADCASTER_IMPLEMENTATION = ["Wowza"]
DEFAULT_EVENT_PATH = getattr(settings, "DEFAULT_EVENT_PATH", "")

class PilotingInterface(ABC):
    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'check_piloting_conf') and
                callable(subclass.check_piloting_conf) and
                hasattr(subclass, 'is_available_to_record') and
                callable(subclass.is_available_to_record) and
                hasattr(subclass, 'is_recording') and
                callable(subclass.is_recording) and
                hasattr(subclass, 'start') and
                callable(subclass.start) and
                hasattr(subclass, 'split') and
                callable(subclass.split) and
                hasattr(subclass, 'stop') and
                callable(subclass.stop) or
                NotImplemented)

    def check_piloting_conf(self) -> bool:
        """Checks the piloting conf value"""
        raise NotImplementedError

    def is_available_to_record(self) -> bool:
        """Checks if the broadcaster is available"""
        raise NotImplementedError

    def is_recording(self) -> bool:
        """Checks if the broadcaster is being recorded"""
        raise NotImplementedError

    def start(self) -> bool:
        """Start the recording"""
        raise NotImplementedError

    def split(self) -> bool:
        """Split the current record"""
        raise NotImplementedError

    def stop(self) -> bool:
        """Stop the recording"""
        raise NotImplementedError


class Wowza(PilotingInterface, ABC):
    def __init__(self, broadcaster: Broadcaster):
        self.broadcaster = broadcaster

    def check_piloting_conf(self) -> bool:
        print("Wowza - Check piloting conf")
        conf = self.broadcaster.piloting_conf
        if not conf:
            print("->piloting_conf value is not set")
            return False
        try:
            decoded = json.loads(conf)
        except:
            print("->piloting_conf has not a valid Json format")
            return False
        if not {"server", "port", "application", "livestream"} <= decoded.keys():
            print(
                "->piloting_conf format value must be like : {'server':'...','port':'...','application':'...','livestream':'...'}")
            return False

        print("->piloting conf OK")
        return True

    def is_available_to_record(self) -> bool:
        print("Wowza - Check availability")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_state_live_stream_recording = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/streamfiles".format(
            server=conf["server"],
            port=conf["port"],
            application=conf["application"],
        )

        response = requests.get(url_state_live_stream_recording,
                                headers={"Accept": "application/json", "Content-Type": "application/json"})

        livestream = conf["livestream"]

        if ".stream" not in livestream:
            return False

        livestream_id = livestream[0:-7]

        for stream in response.json().get('streamFiles'):
            if stream.get("id") == livestream_id:
                return True

        return False

    def is_recording(self) -> bool:
        print("Wowza - Check if is being recorded")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_state_live_stream_recording = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/instances/_definst_/streamrecorders".format(
            server=conf["server"],
            port=conf["port"],
            application=conf["application"]
        )
        response = requests.get(url_state_live_stream_recording, verify=True, headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        if response.json().get('streamrecorders') != None:
            streamrecorders = response.json().get("streamrecorder")
            for streamrecorder in streamrecorders:
                if streamrecorder.get("recorderName") == conf["livestream"]:
                    return True

        return False

    def start(self) -> bool:
        print("Wowza - Start record")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_start_record = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/instances/_definst_/streamrecorders/{livestream}".format(
            server=conf["server"],
            port=conf["port"],
            application=conf["application"],
            livestream=conf["livestream"],
        )
        data = {
            "instanceName": "",
            "fileVersionDelegateName": "",
            "serverName": "",
            "recorderName": "",
            "currentSize": 0,
            "segmentSchedule": "",
            "startOnKeyFrame": True,
            "outputPath": DEFAULT_EVENT_PATH,
            "baseFile": "_pod_test_${RecordingStartTime}",
            "currentFile": "",
            "saveFieldList": [""],
            "recordData": False,
            "applicationName": "",
            "moveFirstVideoFrameToZero": False,
            "recorderErrorString": "",
            "segmentSize": 0,
            "defaultRecorder": False,
            "splitOnTcDiscontinuity": False,
            "version": "",
            "segmentDuration": 0,
            "recordingStartTime": "",
            "fileTemplate": "",
            "backBufferTime": 0,
            "segmentationType": "",
            "currentDuration": 0,
            "fileFormat": "",
            "recorderState": "",
            "option": ""
        }

        response = requests.post(url_start_record, json=data, headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        })
        response_dict = json.loads(response.text)
        #TODO on ne vérifie jamais la valeur du retour

        return True

    def split(self) -> bool:
        print("Wowza - Split record")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_split_record = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/instances/_definst_/streamrecorders/{livestream}/actions/splitRecording".format(
            server=conf["server"],
            port=conf["port"],
            application=conf["application"],
            livestream=conf["livestream"],
        )
        response = requests.put(url_split_record, headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        response_dict = json.loads(response.text)
        print(response_dict)
        #TODO on ne vérifie jamais la valeur du retour
        return True

    def stop(self) -> bool:
        print("Wowza - Stop_record")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_stop_record = "http://{server}:{port}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}/instances/_definst_/streamrecorders/{livestream}/actions/stopRecording".format(
            server=conf["server"],
            port=conf["port"],
            application=conf["application"],
            livestream=conf["livestream"],
        )
        response = requests.put(url_stop_record, headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        response_dict = json.loads(response.text)
        print(response_dict)
        #TODO on ne vérifie jamais la valeur du retour

        return True
