import datetime
import random
import asyncio
import aioconsole
import serial
import time
import re
import json


# Device Address is build as follows:
# 0x743039 -> 29:012345
# Class :   (0x743039  & 0xFC0000) >> 18 = 29
# Id:       (0x743039 & 0x03FFFF) = 012345

class IthoRemoteGatewayError(Exception):
    """Exception to indicate a gateway error."""


class IthoRemoteRFT:
    def __init__(self, port="COM3", baud=115200):
        """Add incoming data to buffer."""
        print("__init__")

        # Serial Port
        self.port = port
        self.baud = baud
        self.timeout = 0  # Non-blocking IO
        self.serial_connection = None
        self.buffer = bytes()

        # Version
        evofw3_min_version = "0.7.0"
        self.evofw3_version = None
        self.log_to_file = True

        # Addresses
        self.remote_address = None
        self.unit_address = None
        # TODO: Sequence number is checked by the Itho machine!
        #  (000 is send after battery swap, so this should be fine)
        self.sequence_number = 0

        # Task variables
        self.is_pairing = False
        self.pairing_timeout = 0

        # TODO TEMP Read remote_address and unit_address from config file.
        self._config_load()

        # Randomly initialise Remote Address when not configured (e.g. 29:012345 & 0x743039)
        if self.remote_address is None:
            self.remote_address = f"29:{random.randint(0, 999999):06d}"

        unit_address_info = f"Remote paired to: {self.unit_address}" if self.unit_address else "Remote not paired"
        print(f"IthoRemoteRFT init OK:\n\r"
              f" Remote address:   {self.remote_address}\n\r"
              f" {unit_address_info}")

        if not self.serial_connection:
            self.serial_connection = serial.Serial(self.port, self.baud, timeout=self.timeout)
            print("IthoRemoteRFT started")

        # Self-test
        self._self_test(evofw3_min_version)

    def _self_test(self, minimal_version):
        """ Blocking self_test:
            When the version number can be retrieved,
            the dongle is operational.
        """
        print("_self_test")

        regex_version = "# evofw3 (?P<VERSION>\\d.\\d.\\d)"

        if not self.serial_connection:
            raise IthoRemoteGatewayError("Gateway not connected!") from Exception

        try:
            # Send the version command
            version_command = "!V\r\n"
            self.serial_connection.write(version_command.encode("utf-8"))

            # Blocking read version number response with timeout
            self.serial_connection.timeout = 1  # Blocking readline

            timeout = time.time() + 5
            while time.time() < timeout:
                data = self.serial_connection.readline().decode().strip()
                match = re.match(regex_version, data)
                if match:
                    version = match.group("VERSION")
                    if version >= minimal_version:
                        print("evofw3 version-check OK: " + version)
                        self.evofw3_version = version
                    else:
                        print("evofw3 version-check fail")
                        raise IthoRemoteGatewayError("Gateway communication fail!") from Exception
                    break

        except serial.SerialException:
            print("IthoRemoteRFT test serial fail")
            raise IthoRemoteGatewayError("Gateway communication fail!") from Exception

    def _config_load(self):
        """ Load configuration from the settings.json file. """
        print("_config_load")

        try:
            with open("settings.json", "r") as f:
                settings = json.load(f)
                self.remote_address = settings.get(
                    "remote_address", self.remote_address
                )
                self.unit_address = settings.get("unit_address", self.unit_address)
                print("Settings loaded")
        except FileNotFoundError:
            print("Settings file does not exist")
        except json.JSONDecodeError:
            print("Settings file corrupt")
        except Exception as e:
            print(f"Settings load error: {e}")

    def _config_save(self):
        """ Store configuration to the settings.json file. """
        print("_config_save")

        settings = {
            "remote_address": self.remote_address,
            "unit_address": self.unit_address
        }

        with open('settings.json', 'w') as f:
            json.dump(settings, f, indent=4)
            print("Settings saved")

    def _send_data(self, data):
        """ Send data to the dongle. """
        # print("_send_data")

        if self.serial_connection:
            self.serial_connection.write(data.encode("utf-8"))
        else:
            raise IthoRemoteGatewayError("Gateway communication lost!") from Exception

    def _receive_data(self):
        """ Non-blocking read data from the dongle.
            Read characters until a newline is received. """
        # print("_receive_data")

        if self.serial_connection:
            self.buffer += self.serial_connection.read()
            if b"\n" in self.buffer:
                data = self.buffer.decode().strip()
                self.buffer = b""
                return data
        else:
            raise IthoRemoteGatewayError("Gateway communication lost!") from Exception

    def _parse_status(self, payload):
        """ Parse status messages into a dictionary. """
        print("_parse_status")

        b = payload

        # unk = b[0:2]

        # Parse air quality (%)
        air_quality_raw = int(b[2:4], 16) / 2
        air_quality = air_quality_raw if 0.0 <= air_quality_raw <= 100.0 else None

        # Parse quality (bitmask)
        quality_base = int(b[4:6], 16)
        quality_base_rh = bool(quality_base & 0b10000000)
        quality_base_co = bool(quality_base & 0b01000000)
        quality_base_voc = bool(quality_base & 0b00100000)
        quality_base_outdoor_improved = bool(quality_base & 0b00010000 == 0)

        # Parse Co2 level (ppm)
        co2_level_raw = int(b[6:10], 16)
        co2_level = co2_level_raw if 0 <= co2_level_raw <= 0x3FFF else None

        # Parse Outdoor/Indoor Humidity (%)
        outdoor_humidity_raw = int(b[10:12], 16)
        outdoor_humidity = (
            outdoor_humidity_raw if 0 <= outdoor_humidity_raw <= 100 else None
        )
        indoor_humidity_raw = int(b[12:14], 16)
        indoor_humidity = (
            indoor_humidity_raw if 0 <= indoor_humidity_raw <= 100 else None
        )

        # Parse HRU channel temperatures (°C)
        exhaust_temperature_raw = int(b[14:18], 16)
        exhaust_temperature_raw -= (
            0x10000 if exhaust_temperature_raw & 0x8000 else 0
        )  # Parse signed int
        exhaust_temperature_raw = exhaust_temperature_raw / 100.0
        exhaust_temperature = (
            exhaust_temperature_raw
            if -273.15 <= exhaust_temperature_raw <= 327.66
            else None
        )

        supply_temperature_raw = int(b[18:22], 16)
        supply_temperature_raw -= (
            0x10000 if supply_temperature_raw & 0x8000 else 0
        )  # Parse signed int
        supply_temperature_raw = supply_temperature_raw / 100.0
        supply_temperature = (
            supply_temperature_raw
            if -273.15 <= supply_temperature_raw <= 327.66
            else None
        )

        indoor_temperature_raw = int(b[22:26], 16)
        indoor_temperature_raw -= (
            0x10000 if indoor_temperature_raw & 0x8000 else 0
        )  # Parse signed int
        indoor_temperature_raw = indoor_temperature_raw / 100.0
        indoor_temperature = (
            indoor_temperature_raw
            if -273.15 <= indoor_temperature_raw <= 327.66
            else None
        )

        outdoor_temperature_raw = int(b[26:30], 16)
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
        capability_flags_raw = int(b[30:34], 16)
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
        capability_flags = ", ".join(set_capabilities) + " Capable"

        # Parse bypass position (%)
        bypass_position_raw = int(b[34:36], 16) / 2
        bypass_position = (
            bypass_position_raw if 0.0 <= bypass_position_raw <= 100.0 else None
        )

        # Flags (bitmask)
        flags_raw = int(b[36:38], 16)
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
            24: "Auto Mode",
            25: "Auto Night",
        }
        flags_active_speed_mode = active_speed_mode_mapping.get(
            flags_active_speed_mode_raw, "Unknown"
        )

        # Parse fan speed inlet/exhaust (%)
        exhaust_fan_speed_raw = int(b[38:40], 16) / 2
        exhaust_fan_speed = (
            exhaust_fan_speed_raw if 0.0 <= exhaust_fan_speed_raw <= 100.0 else None
        )
        inlet_fan_speed_raw = int(b[40:42], 16) / 2
        inlet_fan_speed = (
            inlet_fan_speed_raw if 0.0 <= inlet_fan_speed_raw <= 100.0 else None
        )

        # Parse remaining time (minutes)
        remaining_time = int(b[42:46], 16)

        # Parse heater pre/post (%)
        post_heater_raw = int(b[46:48], 16) / 2
        post_heater = post_heater_raw if 0.0 <= post_heater_raw <= 100.0 else None
        pre_heater_raw = int(b[48:50], 16) / 2
        pre_heater = pre_heater_raw if 0.0 <= pre_heater_raw <= 100.0 else None

        # Parse flow inlet/exhaust (l/s)
        inlet_flow_raw = int(b[50:54], 16)
        inlet_flow = inlet_flow_raw if 0 <= inlet_flow_raw <= 0x7FFF else None
        exhaust_flow_raw = int(b[54:58], 16)
        exhaust_flow = exhaust_flow_raw if 0 <= exhaust_flow_raw <= 0x7FFF else None

        # Dictionary
        self.data = {
            "air_quality": air_quality,
            "quality_base": {
                "Based on TH": quality_base_rh,
                "Based on CO": quality_base_co,
                "Based on VOC": quality_base_voc,
                "Outdoor Improved": quality_base_outdoor_improved,
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

    async def _loop_task(self):
        """ Periodic task to run IthoRemoteRFT. """
        print("_loop_task")

        regex_pattern = "(?P<RSSI>\\d{3}) (?P<VERB> I|RQ|RP| W) (?P<SEQNR>---|\\d{3}) " \
                        "(?P<ADDR1>--:------|\\d{2}:\\d{6}) " \
                        "(?P<ADDR2>--:------|\\d{2}:\\d{6}) " \
                        "(?P<ADDR3>--:------|\\d{2}:\\d{6}) " \
                        "(?P<CODE>[0-9A-F]{4}) (?P<PAYLEN>\\d{3}) (?P<PAYLOAD>[0-9A-F]*)"

        while True:

            # Receive data in the loop
            data = self._receive_data()

            # Process available data
            if data is not None:
                print(data)

                # Log to file?
                if self.log_to_file:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    with open('remote.log', 'a') as f:
                        f.write(f"{timestamp}: {data}\n")

                # Capture groups data using regex
                match = re.match(regex_pattern, data)

                if match:
                    # Handle pairing messages
                    # 072  I 022 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
                    # 070 RQ --- 18:012345 29:012345 --:------ 10E0 001 63
                    if self.is_pairing:
                        if match.group("VERB") == "RQ" and \
                                match.group("CODE") == "10E0" and \
                                match.group("ADDR2") == self.remote_address and \
                                match.group("PAYLOAD") == "63":
                            self.unit_address = match.group("ADDR1")
                            self.is_pairing = False
                            self._config_save()
                            print("Pairing success")

                        if time.time() > self.pairing_timeout:
                            self.unit_address = None
                            self.is_pairing = False
                            print("Pairing timeout")

                    # Handle status messages
                    # 069  I --- 18:012345 --:------ 18:012345 31DA
                    # 029 00F0007FFFEFEF0884079E085A07714000125850FF0000EFEF41E641E6
                    if self.unit_address is not None:
                        if match.group("ADDR1") == self.unit_address and match.group("CODE") == "31DA":
                            print("loop: status message received")
                            # Parse & Print
                            payload = match.group("PAYLOAD")
                            self._parse_status(payload)

            await asyncio.sleep(0)  # Yield control to the event loop

    # Public functions
    def pair(self):
        """ Simulates pressing the pairing button. """
        print("pair")

        # Pair requires remote address in integer format
        convert = self.remote_address.split(":")
        remote_address_int = (int(convert[0]) << 18) + int(convert[1])

        # 074  I 022 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
        # 074  I 022 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
        # 072  I 022 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
        # 070 RQ --- 18:012345 29:012345 --:------ 10E0 001 63
        # 071 RQ --- 18:012345 29:012345 --:------ 10E0 001 63
        # 071 RQ --- 18:012345 29:012345 --:------ 10E0 001 63
        # 068  I --- 18:012345 --:------ 18:012345 31DA 029 00F0007FFFEFEF07CB07C5086E07994000C85850FF0000EFEF402E402E
        if self.unit_address is not None:
            # Send the pair command three times
            for x in range(3):
                data = f" I {self.sequence_number:03} --:------ --:------ {self.remote_address} " \
                       f"1FC9 012 6322F8{remote_address_int:X}0110E0{remote_address_int:X}\r\n"
                self._send_data(data)
                time.sleep(0.5)
                print("Command send: " + data)

            self.sequence_number += 1
            self.pairing_timeout = time.time() + 60
            self.is_pairing = True
            print("Pairing pending")

    def command(self, command):
        """ Simulates pressing the command button(s). """
        print("command")

        # Remote (536-0150)
        #             I 001 --:------ --:------ 29:012345 1FC9 012 6322F87430390110E0743039
        # pair:     ' I 070 --:------ --:------ 29:012345 1FC9 012 6322F874EE110110E074EE11'
        # auto:     ' I 067 --:------ --:------ 29:012345 22F1 003 630304'
        # low:      ' I 063 --:------ --:------ 29:012345 22F1 003 630204'
        # high:     ' I 064 --:------ --:------ 29:012345 22F1 003 630404'
        # timer10:  ' I 058 --:------ --:------ 29:012345 22F3 003 63000A'
        # timer20:  ' I 059 --:------ --:------ 29:012345 22F3 003 630014'
        # timer30:  ' I 060 --:------ --:------ 29:012345 22F3 003 63001E'
        command_map = {
            "auto": "22F1 003 630304",
            "low": "22F1 003 630204",
            "high": "22F1 003 630404",
            "timer10": "22F3 003 63000A",
            "timer20": "22F3 003 630014",
            "timer30": "22F3 003 63001E",
        }

        if command in command_map:
            for x in range(3):
                data = f" I {self.sequence_number:03} --:------ --:------ {self.remote_address} " \
                       f"{command_map[command]}\r\n"
                self._send_data(data)
                time.sleep(0.2)
                print("command: " + data.strip())

            self.sequence_number += 1
            print("command: " + command_map[command])
        else:
            print("Invalid command. Supported commands are: auto, low, high, timer10, timer20, timer30")


async def cli():
    while True:
        try:
            command = await aioconsole.ainput("Enter a command (e.g., "
                                              "'pair', 'auto', 'low', 'high', 'timer10', 'timer20', 'timer30'"
                                              "'test'): \n")
            if command == 'pair':
                itho_remote.pair()
            elif command == 'auto' or command == 'low' or command == 'high' or \
                    command == 'timer10' or command == 'timer20' or command == 'timer30':
                itho_remote.command(command)
            else:
                print("Unknown command")
        except KeyboardInterrupt:
            break

        await asyncio.sleep(0)  # Yield control to the event loop


if __name__ == '__main__':

    loop = None
    itho_remote = IthoRemoteRFT()

    async def main():
        loop_task = asyncio.create_task(itho_remote._loop_task())
        cli_task = asyncio.create_task(cli())
        await asyncio.gather(loop_task, cli_task)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        loop.create_task(main())
        loop.run_forever()
    except KeyboardInterrupt:
        print("Program interrupted by user. Exiting...")
        tasks = asyncio.all_tasks(loop)
        for tasks in tasks:
            tasks.cancel()
    finally:
        loop.close()
