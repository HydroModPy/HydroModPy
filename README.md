# simpleble     [![Documentation Status](https://readthedocs.org/projects/simpleble/badge/?version=latest)](http://simpleble.readthedocs.io/en/latest/?badge=latest)
A high-level OO Python interface to Bluetooth LE on Linux environments. Read the full docs on [ReadTheDocs](http://simpleble.readthedocs.io).

Introduction
============

``simpleble`` is a high-level OO Python package which aims to provide an easy and intuitive way of interacting with nearby Bluetooth Low Energy (BLE) devices (GATT servers). In essence, this package is an extension of the ``bluepy`` package created by Ian Harvey (see [here](https://github.com/IanHarvey/bluepy))

The aim here was to define a single object which would allow users to perform the various operations performed by the ``bluepy.btle.Peripheral``, ``bluepy.btle.Scanner``, ``bluepy.btle.Service`` and ``bluepy.btle.Characteristic`` classes of ``bluepy``, from one central place. This functionality is facilitated by the ``simpleble.SimpleBleClient`` and ``simpleble.SimpleBleDevice`` classes, where the latter is an extention/subclass of ``bluepy.btle.Peripheral``, combined with properties of ``bluepy.btle.ScanEntry``. 

The current implementation has been developed in Python 3 and tested on a Raspberry Pi Zero W, running Raspbian 9 (stretch), but should work with Python 2.7+ (maybe with minor modifications in terms of printing and error handling) and most Debian based OSs. 

Motivation
---------- 

As a newbie experimenter/hobbyist in the field of IoT using BLE communications, I found it pretty hard to identify a Python package which would enable one to use a Raspberry Pi (Zero W inthis case) to swiftly scan, connect to and read/write from/to a nearby BLE device (GATT server). 

This package is intended to provide a quick, as well as (hopefully) easy to undestand, way of getting a simple BLE GATT client up and running, for all those out there, who, like myself, are hands-on learners and are eager to get their hands dirty from early on. 

Limitations
-----------

- As my main use-case scenario was to simply connect two devices, the current version of `simpleble.SimpleBleClient` has been designed and implemented with this use-case in mind. As such, if you are looking for a package to allow you to connect to multiple devices, then know that off-the-self this package DOES NOT allow you to do so. However, implementing such a feature is an easily achievable task, which has been planned for sometime in the near future and if there proves to be interest on the project, I would be happy to speed up the process.

- Only Read and Write operations are currently supported, but I am planning on adding Notifications soon.

- Although the interfacing operations of the `bluepy.btle.Service` and `bluepy.btle.Peripheral` classes have been brought forward to the `simpleble.SimpleBleClient` class, the same has not been done for the `bluepy.btle.Descriptor`, meaning that the `simpleble.SimpleBleClient` cannot be used to directly access the Descriptors. This can however be done easily by obtaining a handle of a `simpleble.SimpleBleDevice` object and calling the superclass `bluepy.btle.Peripheral.getDescriptors` method. 

Example Codes
=============

Installation/Usage:
-------------------
As the package has not been published on PyPi yet, it CANNOT be install using pip. 

For now, the suggested method is to put the file `simpleble.py` in the same directory as your source files and call ``from simpleble import SimpleBleClient, SimpleBleDevice``.

``bluepy`` must also be installed and imported as shown in the example below.
For instructions about how to install, as well as the full documentation of, ``bluepy`` please refer [here](https://github.com/IanHarvey/bluepy)

Search for device, connect and read characteristic
--------------------------------------------------
```python

    """This example demonstrates a simple BLE client that scans for devices, 
    connects to a device (GATT server) of choice and continuously reads a characteristic on that device.

    The GATT Server in this example runs on an ESP32 with Arduino. For the    
    exact script used for this example see https://github.com/nkolban/ESP32_BLE_Arduino/blob/6bad7b42a96f0aa493323ef4821a8efb0e8815f2/examples/BLE_notify/BLE_notify.ino 
    """

    from bluepy.btle import *
    from simpleble import SimpleBleClient, SimpleBleDevice

    # The UUID of the characteristic we want to read and the name of the device # we want to read it from
    Characteristic_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
    Device_Name = "MyESP32"

    # Define our scan and notification callback methods
    def myScanCallback(client, device, isNewDevice, isNewData):
        client._yes = True
        print("#MAC: " + device.addr + " #isNewDevice: " +
              str(isNewDevice) + " #isNewData: " + str(isNewData))
    # TODO: NOTIFICATIONS ARE NOT SUPPORTED YET
    # def myNotificationCallback(client, characteristic, data):
    #     print("Notification received!")
    #     print("  Characteristic UUID: " + characteristic.uuid)
    #     print("  Data: " + str(data))

    # Instantiate a SimpleBleClient and set it's scan callback
    bleClient = SimpleBleClient()
    bleClient.setScanCallback(myScanCallback)
    # TODO: NOTIFICATIONS ARE NOT SUPPORTED YET
    # bleClient.setNotificationCallback(myNotificationCollback)

    # Error handling to detect Keyboard interrupt (Ctrl+C)
    # Loop to ensure we can survive connection drops
    while(not bleClient.isConnected()):
        try:
            # Search for 2 seconds and return a device of interest if found.
            # Internally this makes a call to bleClient.scan(timeout), thus
            # triggering the scan callback method when nearby devices are detected
            device = bleClient.searchDevice(name="MyESP32", timeout=2)
            if(device is not None):
                # If the device was found print out it's info
                print("Found device!!")
                device.printInfo()

                # Proceed to connect to the device
                print("Proceeding to connect....")
                if(bleClient.connect(device)):

                    # Have a peek at the services provided by the device
                    services = device.getServices()
                    for service in services:
                        print("Service ["+str(service.uuid)+"]")

                    # Check to see if the device provides a characteristic with the
                    # desired UUID
                    counter = bleClient.getCharacteristics(
                        uuids=[Characteristic_UUID])[0]
                    if(counter):
                        # If it does, then we proceed to read its value every second
                        while(True):
                            # Error handling ensures that we can survive from
                            # potential connection drops
                            try:
                                # Read the data as bytes and convert to string
                                data_bytes = bleClient.readCharacteristic(
                                    counter)
                                data_str = "".join(map(chr, data_bytes))

                                # Now print the data and wait for a second
                                print("Data: " + data_str)
                                time.sleep(1.0)
                            except BTLEException as e:
                                # If we get disconnected from the device, keep
                                # looping until we have reconnected
                                if(e.code == BTLEException.DISCONNECTED):
                                    bleClient.disconnect()
                                    print(
                                        "Connection to BLE device has been lost!")
                                    break
                                    # while(not bleClient.isConnected()):
                                    #     bleClient.connect(device)

                else:
                    print("Could not connect to device! Retrying in 3 sec...")
                    time.sleep(3.0)
            else:
                print("Device not found! Retrying in 3 sec...")
                time.sleep(3.0)
        except BTLEException as e:
            # If we get disconnected from the device, keep
            # looping until we have reconnected
            if(e.code == BTLEException.DISCONNECTED):
                bleClient.disconnect()
                print(
                    "Connection to BLE device has been lost!")
                break
        except KeyboardInterrupt as e:
            # Detect keyboard interrupt and close down
            # bleClient gracefully
            bleClient.disconnect()
            raise e
```    
