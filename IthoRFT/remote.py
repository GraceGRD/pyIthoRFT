"""Itho RFT Remote."""
import datetime
import logging
import os
import random
import asyncio
import time
import re
import json
import serial

from IthoRFT.const import REQUIRED_EVOFW3_VERSION, TIMEOUT_SELF_TEST, TIMEOUT_PAIRING
# from .const import TIMEOUT_SELF_TEST, TIMEOUT_PAIRING

_LOGGER = logging.getLogger(__name__)


# Device Address is build as follows:
# 0x743039 -> 29:012345
# Class :   (0x743039  & 0xFC0000) >> 18 = 29
# Id:       (0x743039 & 0x03FFFF) = 012345


class IthoRemoteGatewayError(Exception):
    """Exception to indicate a gateway error."""


class IthoRFTRemote:
    """Instance of Itho RFT Remote."""

    def __init__(
            self,
            port: str = "COM3",
            baud: int = 115200,
            remote_address: str | None = None,
            unit_address: str | None = None,
            log_to_file: bool = False
    ):
        """Initialise the Itho RFT Remote connection.
        :param port: The port to access the evofw3 gateway.
        :param baud: The evofw3 baud rate.
        :param remote_address: The virtual address off the remote (if not provided a random address is generated).
        :param unit_address: The unit address which is obtained during pairing.
        :param log_to_file: All data will be logged to remote.log file."""

        self.port = port
        self.baud = baud
        self.remote_address = remote_address
        self.unit_address = unit_address
        self.log_to_file = log_to_file

        _LOGGER.debug(
            f"Itho RFT Remote initialized with the following settings:\n"
            f"  Port: {self.port}\n"
            f"  Baud Rate: {self.baud}\n"
            f"  Remote Address: {self.remote_address}\n"
            f"  Unit Address: {self.unit_address}"
        )

        self.serial_connection = None
        self.task = None
        self.data_callback = None
        self.pair_callback = None
        self.data = {}
        self.is_pairing = False
        self.pairing_timeout = 0

        # TODO: Sequence number is checked by the Itho machine!
        #  (000 is send after battery swap, so 0 should be fine)
        self.sequence_number = 0

        # Randomise Remote Address when not configured (e.g. 29:012345 & 0x743039)
        if self.remote_address is None:
            self.remote_address = f"29:{random.randint(0, 0x3FFFF):06d}"

        unit_address_info = (
            f"Remote paired to: {self.unit_address}"
            if self.unit_address
            else "Remote not paired"
        )
        _LOGGER.debug(
            f"Init OK:\n\r"
            f" Remote address:   {self.remote_address}\n\r"
            f" {unit_address_info}"
        )

        if not self.serial_connection:
            # Serial in non-blocking IO mode
            self.serial_connection = serial.Serial(
                self.port, self.baud, timeout=0
            )
            _LOGGER.debug("Started")

    def _config_load(self):
        """"Load Itho RFT Remote configuration from ./settings.json file."""

        _LOGGER.debug("Itho RFT Remote load from ./settings.json")

        try:
            with open("settings.json", "r", encoding="utf8") as file:
                settings = json.load(file)
                self.remote_address = settings.get(
                    "remote_address", self.remote_address
                )
                self.unit_address = settings.get("unit_address", self.unit_address)
                _LOGGER.debug("Settings loaded")
        except FileNotFoundError:
            _LOGGER.error("Settings file does not exist")
        except json.JSONDecodeError:
            _LOGGER.error("Settings file corrupt")

    def _config_save(self):
        """"Save Itho RFT Remote configuration to ./settings.json file."""

        _LOGGER.debug("Itho RFT Remote saving to ./settings.json")

        settings = {
            "remote_address": self.remote_address,
            "unit_address": self.unit_address,
        }

        with open("settings.json", "w", encoding="utf8") as file:
            json.dump(settings, file, indent=4)
            print("Settings saved")

    def _log_to_file(self, data):
        """"Log data to itho_remote_<date>.log file and keep 7 day history."""

        log_directory = os.getcwd()
        logfile_date = datetime.datetime.now().strftime("%Y-%m-%d")
        log_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_filename = os.path.join(log_directory, f"itho_remote_{logfile_date}.log")

        with open(log_filename, "a", encoding="utf8") as file:
            file.write(f"{log_timestamp}: {data}\n")

        log_files = sorted([file for file in os.listdir(log_directory) if
                            file.endswith('.log') and file.startswith('itho_remote')])
        if len(log_files) > 7:
            for old_log_file in log_files[:-7]:
                os.remove(os.path.join(log_directory, old_log_file))

    def _send_data(self, data):
        """"Send blocking data to evofw3 gateway."""

        if self.serial_connection:
            self.serial_connection.write(data.encode("utf-8"))
        else:
            raise IthoRemoteGatewayError("Gateway communication lost!") from Exception

    def _receive_data(self):
        """"Receive non-blocking data (until newline) from the evofw3 gateway."""

        if self.serial_connection:
            data = self.serial_connection.readline().decode().strip()
            return data if data else None

        else:
            raise IthoRemoteGatewayError("Gateway communication lost!") from Exception

    async def _loop_task(self):
        """"Periodic task to run Itho RFT Remote."""

        regex_pattern = (
            "(?P<RSSI>\\d{3}) (?P<VERB> I|RQ|RP| W) (?P<SEQNR>---|\\d{3}) "
            "(?P<ADDR1>--:------|\\d{2}:\\d{6}) "
            "(?P<ADDR2>--:------|\\d{2}:\\d{6}) "
            "(?P<ADDR3>--:------|\\d{2}:\\d{6}) "
            "(?P<CODE>[0-9A-F]{4}) (?P<PAYLEN>\\d{3}) (?P<PAYLOAD>[0-9A-F]*)"
        )

        try:
            while True:
                await asyncio.sleep(1)  # Yield control to the event loop

                # Receive data in the loop (can be multiple lines)
                while True:
                    data = self._receive_data()
                    if data is None:
                        break  # No data available

                    # Process available data
                    _LOGGER.debug(data)

                    # Log to file?
                    if self.log_to_file:
                        self._log_to_file(data)

                    # Capture groups data using regex
                    match = re.match(regex_pattern, data)
                    if match:

                        # Verify payload length
                        if int(len(match.group("PAYLOAD")) / 2) != int(match.group("PAYLEN")):
                            continue

                        # Handle pairing messages
                        # 072  I 022 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
                        # 070 RQ --- 18:012345 29:012345 --:------ 10E0 001 63
                        if self.is_pairing:
                            if (
                                    match.group("VERB") == "RQ"
                                    and match.group("CODE") == "10E0"
                                    and match.group("ADDR2") == self.remote_address
                                    and match.group("PAYLOAD") == "63"
                            ):
                                self.unit_address = match.group("ADDR1")
                                self.is_pairing = False
                                # self._config_save()
                                _LOGGER.info("Pairing success")

                                # Call pair callback (return remote and unit address on success)
                                if self.pair_callback is not None:
                                    self.pair_callback(self.remote_address, self.unit_address)

                            if time.time() > self.pairing_timeout:
                                self.unit_address = None
                                self.is_pairing = False

                                _LOGGER.warning("Pairing timeout")

                        # Handle status messages
                        # 069  I --- 18:012345 --:------ 18:012345 31DA
                        # 029 00F0007FFFEFEF0884079E085A07714000125850FF0000EFEF41E641E6
                        if self.unit_address is not None:
                            if (
                                    match.group("ADDR1") == self.unit_address
                                    and match.group("CODE") == "31DA"
                            ):
                                _LOGGER.debug("unit status message received")

                                # Parse & Print
                                payload = match.group("PAYLOAD")
                                self._parse_status(payload)
                                # Pretty print dictionary as json
                                pretty_data = json.dumps(self.data, indent=4)
                                _LOGGER.debug(pretty_data)

                                # Call data callback
                                if self.data_callback is not None:
                                    self.data_callback(self.data)

        except asyncio.CancelledError:
            _LOGGER.warning("Itho RFT Remote task cancelled")
        finally:
            self.task = None

    def _parse_status(self, payload):
        """"Parse unit status messages."""

        pos = payload

        # unk = b[0:2]

        # Parse air quality (%)
        air_quality_raw = int(pos[2:4], 16) / 2
        air_quality = air_quality_raw if 0.0 <= air_quality_raw <= 100.0 else None

        # Parse quality (bitmask)
        quality_base = int(pos[4:6], 16)
        quality_base_rh = bool(quality_base & 0b10000000)
        quality_base_co = bool(quality_base & 0b01000000)
        quality_base_voc = bool(quality_base & 0b00100000)
        quality_base_outdoor_improved = bool(quality_base & 0b00010000 == 0)

        # Parse Co2 level (ppm)
        co2_level_raw = int(pos[6:10], 16)
        co2_level = co2_level_raw if 0 <= co2_level_raw <= 0x3FFF else None

        # Parse Outdoor/Indoor Humidity (%)
        outdoor_humidity_raw = int(pos[10:12], 16)
        outdoor_humidity = (
            outdoor_humidity_raw if 0 <= outdoor_humidity_raw <= 100 else None
        )
        indoor_humidity_raw = int(pos[12:14], 16)
        indoor_humidity = (
            indoor_humidity_raw if 0 <= indoor_humidity_raw <= 100 else None
        )

        # Parse HRU channel temperatures (°C)
        exhaust_temperature_raw = int(pos[14:18], 16)
        exhaust_temperature_raw -= (
            0x10000 if exhaust_temperature_raw & 0x8000 else 0
        )  # Parse signed int
        exhaust_temperature_raw = exhaust_temperature_raw / 100.0
        exhaust_temperature = (
            exhaust_temperature_raw
            if -273.15 <= exhaust_temperature_raw <= 327.66
            else None
        )

        supply_temperature_raw = int(pos[18:22], 16)
        supply_temperature_raw -= (
            0x10000 if supply_temperature_raw & 0x8000 else 0
        )  # Parse signed int
        supply_temperature_raw = supply_temperature_raw / 100.0
        supply_temperature = (
            supply_temperature_raw
            if -273.15 <= supply_temperature_raw <= 327.66
            else None
        )

        indoor_temperature_raw = int(pos[22:26], 16)
        indoor_temperature_raw -= (
            0x10000 if indoor_temperature_raw & 0x8000 else 0
        )  # Parse signed int
        indoor_temperature_raw = indoor_temperature_raw / 100.0
        indoor_temperature = (
            indoor_temperature_raw
            if -273.15 <= indoor_temperature_raw <= 327.66
            else None
        )

        outdoor_temperature_raw = int(pos[26:30], 16)
        outdoor_temperature_raw -= (
            0x10000 if outdoor_temperature_raw & 0x8000 else 0
        )  # Parse signed int
        outdoor_temperature_raw = outdoor_temperature_raw / 100.0
        outdoor_temperature = (
            outdoor_temperature_raw
            if -273.15 <= outdoor_temperature_raw <= 327.66
            else None
        )

        # Capability flags (bitmask)
        capability_flags_raw = int(pos[30:34], 16)
        capability_names = [
            "Off",
            "Away",
            "Timer",
            "Boost",
            "Auto",
            "Speed 4",
            "Speed 5",
            "Speed 6",
            "Speed 7",
            "Speed 8",
            "Speed 9",
            "Speed 10",
            "Night",
            "Reserved",
            "Post Heater",
            "Pre Heater",
        ]
        set_capabilities = [
            capability_names[i]
            for i in range(16)
            if capability_flags_raw & (1 << (15 - i))
        ]
        capability_flags = ", ".join(set_capabilities)

        # Parse bypass position (%)
        bypass_position_raw = int(pos[34:36], 16) / 2
        bypass_position = (
            bypass_position_raw if 0.0 <= bypass_position_raw <= 100.0 else None
        )

        # Flags (bitmask)
        flags_raw = int(pos[36:38], 16)
        flags_fault_active = bool(flags_raw & 0b10000000)
        flags_filter_dirty = bool(flags_raw & 0b01000000)
        flags_defrost_active = bool(flags_raw & 0b00100000)
        flags_active_speed_mode_raw = int(flags_raw & 0b00011111)
        active_speed_mode_mapping = {
            0: "OFF",
            1: "Speed 1",
            2: "Speed 2",
            3: "Speed 3",
            4: "Speed 4",
            5: "Speed 5",
            6: "Speed 6",
            7: "Speed 7",
            8: "Speed 8",
            9: "Speed 9",
            10: "Speed 10",
            11: "Speed 1 Temporary Override",
            12: "Speed 2 Temporary Override",
            13: "Speed 3 Temporary Override",
            14: "Speed 4 Temporary Override",
            15: "Speed 5 Temporary Override",
            16: "Speed 6 Temporary Override",
            17: "Speed 7 Temporary Override",
            18: "Speed 8 Temporary Override",
            19: "Speed 9 Temporary Override",
            20: "Speed 10 Temporary Override",
            21: "Away",
            22: "Abs Minimum Speed",
            23: "Abs Maximum Speed",
            24: "Auto",
            25: "Night",
        }
        flags_active_speed_mode = active_speed_mode_mapping.get(
            flags_active_speed_mode_raw, "Unknown"
        )

        # Parse fan speed inlet/exhaust (%)
        exhaust_fan_speed_raw = int(pos[38:40], 16) / 2
        exhaust_fan_speed = (
            exhaust_fan_speed_raw if 0.0 <= exhaust_fan_speed_raw <= 100.0 else None
        )
        inlet_fan_speed_raw = int(pos[40:42], 16) / 2
        inlet_fan_speed = (
            inlet_fan_speed_raw if 0.0 <= inlet_fan_speed_raw <= 100.0 else None
        )

        # Parse remaining time (minutes)
        remaining_time = int(pos[42:46], 16)

        # Parse heater pre/post (%)
        post_heater_raw = int(pos[46:48], 16) / 2
        post_heater = post_heater_raw if 0.0 <= post_heater_raw <= 100.0 else None
        pre_heater_raw = int(pos[48:50], 16) / 2
        pre_heater = pre_heater_raw if 0.0 <= pre_heater_raw <= 100.0 else None

        # Parse flow inlet/exhaust (m3/h)
        inlet_flow_raw = int(pos[50:54], 16)
        inlet_flow = inlet_flow_raw / 100.0 if 0 <= inlet_flow_raw <= 0x7FFF else None
        exhaust_flow_raw = int(pos[54:58], 16)
        exhaust_flow = exhaust_flow_raw / 100.0 if 0 <= exhaust_flow_raw <= 0x7FFF else None

        # Dictionary
        self.data = {
            "air_quality": air_quality,
            "quality_base": {
                "th": quality_base_rh,
                "co": quality_base_co,
                "voc": quality_base_voc,
                "outdoor_improved": quality_base_outdoor_improved,
            },
            "co2_level": co2_level,
            "outdoor_humidity": outdoor_humidity,
            "indoor_humidity": indoor_humidity,
            "exhaust_temperature": exhaust_temperature,
            "supply_temperature": supply_temperature,
            "indoor_temperature": indoor_temperature,
            "outdoor_temperature": outdoor_temperature,
            "capability_flags": capability_flags,
            "bypass_position": bypass_position,
            "flags": {
                "fault_active": flags_fault_active,
                "filter_dirty": flags_filter_dirty,
                "defrost_active": flags_defrost_active,
                "active_speed_mode": flags_active_speed_mode,
            },
            "exhaust_fan_speed": exhaust_fan_speed,
            "inlet_fan_speed": inlet_fan_speed,
            "remaining_time": remaining_time,
            "pos_theater": post_heater,
            "pre_heater": pre_heater,
            "inlet_flow": inlet_flow,
            "exhaust_flow": exhaust_flow,
        }

    def self_test(self):
        """"Blocking self-test Itho RFT Remote."""

        # When the version number can be retrieved, the dongle is operational.
        _LOGGER.debug("Itho RFT Remote evofw3 self-test")

        regex_version = "# evofw3 (?P<VERSION>\\d.\\d.\\d)"

        if not self.serial_connection:
            raise IthoRemoteGatewayError("Gateway not connected!") from Exception

        try:
            # Send the version command
            version_command = "!V\r\n"
            self.serial_connection.write(version_command.encode("utf-8"))

            # TODO: Blocking read version number response with timeout
            self.serial_connection.timeout = 1  # Blocking readline

            timeout = time.time() + TIMEOUT_SELF_TEST
            while time.time() < timeout:
                data = self.serial_connection.readline().decode().strip()
                match = re.match(regex_version, data)
                if match:
                    version = match.group("VERSION")
                    if version >= REQUIRED_EVOFW3_VERSION:
                        _LOGGER.debug("evofw3 version-check OK: " + version)
                    else:
                        _LOGGER.error("evofw3 version-check fail")
                        raise IthoRemoteGatewayError(
                            "Gateway communication fail!"
                        ) from Exception
                    break

            if time.time() >= timeout:
                _LOGGER.error("evofw3 version-check timeout")
                raise IthoRemoteGatewayError(
                    "Gateway communication fail!"
                ) from Exception

        except serial.SerialException:
            raise IthoRemoteGatewayError("Gateway communication fail!") from Exception

    # Public functions
    def register_pair_callback(self, callback):
        """"Register callback on Itho RFT Remote pairing success."""

        self.pair_callback = callback

    def register_data_callback(self, callback):
        """"Register callback on Itho RFT Remote data updates."""

        self.data_callback = callback

    def start_task(self):
        """"Starts Itho RFT Remote async task."""

        if self.task is None:
            self.task = asyncio.create_task(self._loop_task())
            _LOGGER.debug("Itho RFT Remote task started")
        else:
            _LOGGER.warning("Itho RFT Remote task is already running")

    def stop_task(self):
        """"Stops Itho RFT Remote async task."""

        if self.task:
            self.task.cancel()
            _LOGGER.debug("Itho RFT Remote task stopped")
        else:
            _LOGGER.warning("Itho RFT Remote task is already stopped")

    def pair(self):
        """"Starts Itho RFT Remote pairing procedure."""

        # Pair requires remote address in integer format
        convert = self.remote_address.split(":")
        remote_address_int = (int(convert[0]) << 18) + int(convert[1])

        # 074  I 022 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
        # 074  I 022 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
        # 072  I 022 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
        # 070 RQ --- 18:012345 29:012345 --:------ 10E0 001 63
        # 071 RQ --- 18:012345 29:012345 --:------ 10E0 001 63
        # 071 RQ --- 18:012345 29:012345 --:------ 10E0 001 63
        # 068  I --- 18:012345 --:------ 18:012345 31DA 029
        #   00F0007FFFEFEF07CB07C5086E07994000C85850FF0000EFEF402E402E
        if self.remote_address is not None:
            # Send the pair command
            data = (
                f" I {self.sequence_number:03} --:------ --:------ {self.remote_address} "
                f"1FC9 012 6322F8{remote_address_int:X}0110E0{remote_address_int:X}\r\n"
            )
            self._send_data(data)
            _LOGGER.debug("Itho RFT Remote pairing command send: " + data)

            self.sequence_number += 1
            self.pairing_timeout = time.time() + TIMEOUT_PAIRING
            self.is_pairing = True
            _LOGGER.info("Itho RFT Remote pairing pending...")

    def command(self, command):
        """"Sends Itho RFT Remote commands."""

        # Remote (536-0150)
        #             I 001 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
        # pair:     ' I 070 --:------ --:------ 29:012345 1FC9 012 6322F874EE110110E074EE11'
        # night:    ' I 109 --:------ --:------ 29:060945 22F8 003 630203'
        # auto:     ' I 067 --:------ --:------ 29:012345 22F1 003 630304'
        # low:      ' I 063 --:------ --:------ 29:012345 22F1 003 630204'
        # high:     ' I 064 --:------ --:------ 29:012345 22F1 003 630404'
        # timer10:  ' I 058 --:------ --:------ 29:012345 22F3 003 63000A'
        # timer20:  ' I 059 --:------ --:------ 29:012345 22F3 003 630014'
        # timer30:  ' I 060 --:------ --:------ 29:012345 22F3 003 63001E'
        command_map = {
            "night": "22F8 003 630203",
            "auto": "22F1 003 630304",
            "low": "22F1 003 630204",
            "high": "22F1 003 630404",
            "timer10": "22F3 003 63000A",
            "timer20": "22F3 003 630014",
            "timer30": "22F3 003 63001E",
        }

        if command in command_map:
            data = (
                f" I {self.sequence_number:03} --:------ --:------ {self.remote_address} "
                f"{command_map[command]}\r\n"
            )
            self._send_data(data)
            self.sequence_number += 1
            _LOGGER.debug("Itho RFT Remote {command} command send: " + data.strip())

        else:
            _LOGGER.warning(
                "Invalid command. Supported commands: night, auto, low, high, timer10, timer20, timer30"
            )

    def request_data(self):
        """"Requests Itho RFT Remote data [31DA]."""

        # This is not a command supported by the original remote however this seems to work :)

        # Co2 sensor (04-00045)
        # 068 RQ --- 29:012345 18:012345 --:------ 31DA 001 00
        # 086 RP --- 18:012345 29:012345 --:------ 31DA 029
        # 00C84002A5EFEF07F5087F082C082E4808C81800FF0000EFEF13F613F6

        data = f"RQ --- {self.remote_address} {self.unit_address} --:------ 31DA 001 00\r\n"
        self._send_data(data)
        _LOGGER.debug("Itho RFT Remote data request send: " + data.strip())
