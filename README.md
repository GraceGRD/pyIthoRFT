# pyIthoRFT

[![PyPI version](https://badge.fury.io/py/pyIthoRFT.svg)](https://badge.fury.io/py/pyIthoRFT) 
<a href="https://github.com/ambv/black/blob/master/LICENSE"><img alt="License: MIT" src="https://black.readthedocs.io/en/stable/_static/license.svg"></a>

Python3 library for Itho RFT

Controls Itho ventilation boxes / Heat Recovery Units (HRU).

This project was developed during my free time, and contributions are welcome.

## Overview
This library emulates the Itho RFT AUTO (536-0150) remote using the [evofw3 Gateway by ghoti57](https://github.com/ghoti57/evofw3) allowing the control of Itho ventilation / HRU units.

The primary objective for this library is to be integrated with Home Assistant as a custom_component. 

**The supported functionality includes:**

- Pairing with the HRU using a randomly generated `remote_address`.
- Saving and loading the paired `remote_address` and `unit_address`.
- Sending remote commands (`auto`, `low`, `high`, and `timer10/20/30`).
- Parsing HRU data such as `active_speed_mode`, `temperature`, `fault_active` and `filter_dirty`)
- Logging gateway data to `remote.log`.

**Upcoming steps:**

- Integration of the library into Home Assistant or HACS (Home Assistant Community Store) -> work-in-progress.

## Setup

This project is compatible with any **evofw3**-compatible gateway. While I've observed stability issues with gateways utilizing the green CC1101 wireless RF module, I've opted to create my own solution.

The gateway I employ is a DIY homemade setup, comprising an **Arduino Pro Micro 3V3** microcontroller and an **EBYTE E07-900M10S** wireless RF module.

Make sure your software version is at least **v0.7.0** or later.

Please note that this implementation has only been tested on the **Itho HRU ECO300** model.

Feel free to let me know if you have any further questions or need assistance with anything else!

## Install
```
pip3 install pyIthoRFT
```

## Example:
```
TODO
```
