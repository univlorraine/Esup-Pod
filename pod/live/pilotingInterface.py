import http
import json
import logging
import re
from abc import ABC

import requests
from django.conf import settings

from .models import Broadcaster

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
                callable(subclass.stop) and
                hasattr(subclass, 'get_info_current_record') and
                callable(subclass.get_info_current_record) or
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

    def start(self, event_id, login) -> bool:
        """Start the recording"""
        raise NotImplementedError

    def split(self) -> bool:
        """Split the current record"""
        raise NotImplementedError

    def stop(self) -> bool:
        """Stop the recording"""
        raise NotImplementedError

    def get_info_current_record(self) -> dict:
        """Get info of current record"""
        raise NotImplementedError


class Wowza(PilotingInterface, ABC):
    def __init__(self, broadcaster: Broadcaster):
        self.broadcaster = broadcaster
        self.url = None
        if self.check_piloting_conf():
            conf = json.loads(self.broadcaster.piloting_conf)
            self.url = "{server_url}/v2/servers/_defaultServer_/vhosts/_defaultVHost_/applications/{application}" \
                .format(
                    server_url=conf["server_url"],
                    application=conf["application"],
                )

    def check_piloting_conf(self) -> bool:
        logging.debug("Wowza - Check piloting conf")
        conf = self.broadcaster.piloting_conf
        if not conf:
            logging.error("'piloting_conf' value is not set for '"+self.broadcaster.name +"' broadcaster.")
            return False
        try:
            decoded = json.loads(conf)
        except:
            logging.error("'piloting_conf' has not a valid Json format for '"+self.broadcaster.name +"' broadcaster.")
            return False
        if not {"server_url", "application", "livestream"} <= decoded.keys():
            logging.error(
                "'piloting_conf' format value for '"+self.broadcaster.name +"' broadcaster must be like : "
                "{'server_url':'...','application':'...','livestream':'...'}")
            return False

        logging.debug("->piloting conf OK")
        return True

    def is_available_to_record(self) -> bool:
        logging.debug("Wowza - Check availability")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_state_live_stream_recording = self.url + "/instances/_definst_/incomingstreams/" + conf["livestream"]

        response = requests.get(url_state_live_stream_recording,
                                headers={"Accept": "application/json", "Content-Type": "application/json"})

        if response.status_code == http.HTTPStatus.OK:
            if response.json().get('isConnected') is True and response.json().get('isRecordingSet') is False:
                return True

        return False

    def is_recording(self) -> bool:
        logging.debug("Wowza - Check if is being recorded")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_state_live_stream_recording = self.url + "/instances/_definst_/incomingstreams/" + conf["livestream"]

        response = requests.get(url_state_live_stream_recording,
                                headers={"Accept": "application/json", "Content-Type": "application/json"})

        if response.status_code == http.HTTPStatus.OK:
            return response.json().get('isConnected') and response.json().get('isRecordingSet')

        return False

    def get_current_record(self):
        # TODO non utilisé et non déclaré mais peut être utile
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_state_live_stream_recording = self.url + "/instances/_definst_/streamrecorders"

        response = requests.get(url_state_live_stream_recording, verify=True, headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        streamrecorder = response.json().get('streamrecorder')
        for prop in streamrecorder:
            if prop.get("recorderName") == conf["livestream"]:
                return streamrecorder

        return None

    def start(self, event_id=None, login=None) -> bool:
        logging.debug("Wowza - Start record")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_start_record = self.url + "/instances/_definst_/streamrecorders/" + conf["livestream"]
        filename = self.broadcaster.slug
        if event_id is not None:
            filename = event_id + "_" + filename
        elif login is not None:
            filename = login + "_" + filename
        data = {
            "instanceName": "",
            "fileVersionDelegateName": "",
            "serverName": "",
            "recorderName": "",
            "currentSize": 0,
            "segmentSchedule": "",
            "startOnKeyFrame": True,
            "outputPath": DEFAULT_EVENT_PATH,
            "baseFile": "",
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
            "fileTemplate": filename + "_${RecordingStartTime}_${SegmentNumber}",
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

        return response.status_code == http.HTTPStatus.CREATED

    def split(self) -> bool:
        logging.debug("Wowza - Split record")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_split_record = self.url + "/instances/_definst_/streamrecorders/" + conf["livestream"] + "/actions/splitRecording"
        response = requests.put(url_split_record, headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        return response.status_code == http.HTTPStatus.OK

    def stop(self) -> bool:
        logging.debug("Wowza - Stop_record")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_stop_record = self.url + "/instances/_definst_/streamrecorders/" + conf[
            "livestream"] + "/actions/stopRecording"
        response = requests.put(url_stop_record, headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        return response.status_code == http.HTTPStatus.OK

    def get_info_current_record(self):
        logging.debug("Wowza - Get info from current record")
        json_conf = self.broadcaster.piloting_conf
        conf = json.loads(json_conf)
        url_state_live_stream_recording = self.url + "/instances/_definst_/streamrecorders/" + conf["livestream"]

        response = requests.get(url_state_live_stream_recording, verify=True, headers={
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

        if response.status_code != http.HTTPStatus.OK:
            return {
                'currentFile': '',
                'segmentNumber': '',
                'outputPath': '',
                'segmentDuration': '',
            }

        segment_number = ""
        current_file = response.json().get("currentFile")

        try:
            ending = current_file.split("_")[-1]
            if re.match(r'\d+\.', ending):
                number = ending.split(".")[0]
                segment_number = int(number) + 1
                segment_number = "(" + str(segment_number) + ")"
        except :
            pass

        return {
            'currentFile': current_file,
            'segmentNumber': segment_number,
            'outputPath': response.json().get("outputPath"),
            'segmentDuration': response.json().get("segmentDuration"),
        }

