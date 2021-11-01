# pykaleidescape

A python library for controlling Kaleidescape devices via the Kaleidescape System Control Protocol.

## Overview

**pykaleidescape** is a python `asyncio` library providing access to a Kaleidescape system of one or more devices,
facilitating the creation of your own controller. Once connected to a device, each device in the system will have a
representative `Device` object that mirrors its hardware state, as well as methods for issuing commands. An event
dispatching system is also available to signal your controller of changes to connection and device state.

The
[Kaleidescape System Control Protocol](https://www.kaleidescape.com/wp-content/uploads/Kaleidescape-System-Control-Protocol-Reference-Manual.pdf)
is used for communication with hardware devices. It's an important reference while developing your controller code
utilizing pykaleidescape, specifically the description of the commands and events the protocol exposes. Also, the 
integration section of that document contains some great ideas for automations.

Note that `pykaleidescape` only supports Strato players at this time. 

## Installation

```
pip install pykaleidescape
```

## Usage

Checkout the [examples](examples) directory for more in depth examples.

```python
import asyncio
from kaleidescape import Kaleidescape

async def main():
    kaleidescape = Kaleidescape('my-kaleidescape.local')  # or "my-kaleidescape" on Windows
    await kaleidescape.connect(auto_reconnect=True)
    device = await kaleidescape.get_device()
    print(f"Power state is currently: {device.power.state}")
    await kaleidescape.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

## API

To get started, here is an overview of some of the more important class methods available. As mentioned above
`pykaleidescape` makes extensive use of `asyncio`, so you are assured it will never block your own controller code.

### Connecting

Your controller code should start by instantiating a new `Kaleidescape` object.

```python
kaleidescape = Kaleidescape('my-kaleidescape.local')  # or "my-kaleidescape" on Windows
```

As shown, you will need to provide a hostname to connect to, which should be the same hostname used to configure the
Kaleidescape system. Here is a great document on what to connect to:
https://support.kaleidescape.com/article/Accessing-the-Browser-Interface. Note that even though you are connecting to a
single device (the **local device**), `pykaleidescape` provides access to an entire multi-device system via command
routing through the local device.

Next you will then usually connect to the system with the `Kaleidescape::connect()` method. Connections support a
reconnection mechanism to ensure connections are reestablished in the event of a disconnect.

```python
await kaleidescape.connect(auto_reconnect=True, reconnect_delay=10)
```

Later you can disconnect with `Kaleidescape::disconnect()`.

```python
await kaleidescape.disconnect()
```

### Devices

Once connected, you can get a handle to the **local device**, or all devices, with the `Kaleidescape::get_device()`
and `Kaleidescape::get_devices()` methods. These return a `Device` object (or a list) which provides a representation
of the state of the Kaleidescape device. The **local device** is always the first Device in the list that
`Kaleidescape::get_devices()` returns.

```python
device = await kaleidescape.get_device()
devices = await kaleidescape.get_devices()
```

In addition to state, devices provide methods for issuing commands. As mentioned above, refer to the Kaleidescape
System Control Protocol manual for reference. But here are a few primary ones.

```python
await device.leave_standby()
await device.enter_standby()
await device.play()
await device.pause()
await device.stop()
```

### State

Once you have a handle to a `Device`, it can be used to read its current state. Because there are so many properties
of a device's state, they are organized into four groups. 

* system
* osd
* movie
* integration

See the [Device class](kaleidescape/device.py) for a complete
list of the properties of each group. Here are some random examples:

```python
print(device.power.state)  # standby
print(device.osd.highlighted)  # "26-0.0-S_c446c8e2"
print(device.movie.title)  # "Turtle Odyssey"
print(device.automation.movie_location)  # "credits"
```

### Signals and Events

To receive notification of changes to system state (as events), you just need to connect `pykaleidescape` signals to
your controller handlers. There are two type of signals your can connect, and each of those signals provides one or
more events.

#### SIGNAL_CONTROLLER_EVENT

The controller signal (`const.SIGNAL_CONTROLLER_EVENT`) emits changes to the connection state and devices in the system.
Your handler will be called with a single parameter, one of the following event names:

* `const.EVENT_CONTROLLER_CONNECTED`: Emitted when a connection is established to the local device.
* `const.EVENT_CONTROLLER_DISCONNECTED`: Emitted when the connection to the local devices is broken.
* `const.EVENT_CONTROLLER_UPDATED` : Emitted when devices have been added or removed to the system (since startup).

Example:

```python
def handle(event: str):
    if event == const.EVENT_CONTROLLER_UPDATED:
        # You might call kaleidescape.get_devices() and sync changes with your own state
    
kaleidescape.dispatcher.connect(const.SIGNAL_CONTROLLER_EVENT, handle)
```

#### SIGNAL_DEVICE_EVENT

The device signal (`const.SIGNAL_DEVICE_EVENT`) emits changes in device state. The events it emits are the events
listed in the
[Kaleidescape System Control Protocol](https://www.kaleidescape.com/wp-content/uploads/Kaleidescape-System-Control-Protocol-Reference-Manual.pdf)
manual (there are many). Your handler will be called with two parameters, the device_id that was updated, and the name
of the event that was emitted.

Example:
 
```python
def handle(device_id: str, event: str):
    # You might sync your own entity state with this device, which might trigger your integrations.

kaleidescape.dispatcher.connect(const.SIGNAL_DEVICE_EVENT, handle)
```
