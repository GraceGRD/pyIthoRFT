# IthoRemoteRFT

Itho RFT AUTO (536-0150) Virtual Remote Using the [evofw3 Gateway by ghoti57](https://github.com/ghoti57/evofw3).

This project was developed during my free time, and contributions are welcome.

## Overview

The primary objective of this project is to seamlessly integrate the Itho Heat-Recovery-Unit (HRU) with Home Assistant by emulating an RFT remote. This integration enables control of the HRU installation without disrupting the functionality of paired physical remotes. Unlike some other solutions that copy IDs from paired physical remotes, potentially causing odd behavior, this project ensures smooth operation.

**The supported functionality includes:**

- Pairing with the HRU using a randomly generated `remote_address`.
- Saving and loading the paired `remote_address` and `unit_address`.
- Sending remote commands (`auto`, `low`, `high`, and `timer10/20/30`).
- Logging gateway data to `remote.log`.

**Upcoming steps:**

- Creation of a Python library package for easy installation via pip.
- Integration of the library into Home Assistant or HACS (Home Assistant Community Store).

## Setup

This project is compatible with any **evofw3**-compatible gateway. While I've observed stability issues with gateways utilizing the green CC1101 wireless RF module, I've opted to create my own solution.

The gateway I employ is a DIY homemade setup, comprising an **Arduino Pro Micro 3V3** microcontroller and an **EBYTE E07-900M10S** wireless RF module.

Make sure your software version is at least **v0.7.0** or later.

Please note that this implementation has been tested on the **Itho HRU ECO300** model.

Feel free to let me know if you have any further questions or need assistance with anything else!
