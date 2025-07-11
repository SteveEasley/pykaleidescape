import asyncio
import logging
from datetime import datetime
from kaleidescape import Kaleidescape, const

# Set up logging to see debug information
logging.basicConfig(level=logging.INFO)

# pylint: disable=all


async def controller_event_handler(event: str):
    """Handle controller events (connection, disconnection, device updates)"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] CONTROLLER EVENT: {event}")
    
    if event == const.EVENT_CONTROLLER_CONNECTED:
        print("  → Connected to Kaleidescape system")
    elif event == const.EVENT_CONTROLLER_DISCONNECTED:
        print("  → Disconnected from Kaleidescape system")
    elif event == const.EVENT_CONTROLLER_UPDATED:
        print("  → Device configuration updated")


async def device_event_handler(device_id: str, event: str, *args):
    """Handle all device events and output them with timestamps"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if args:
        # This is an unregistered event with raw data
        response = args[0]
        print(f"[{timestamp}] DEVICE EVENT (UNREGISTERED): {device_id} → {event}")
        print(f"  Raw data: {response}")
        if hasattr(response, 'message'):
            print(f"  Full message: {response.message}")
        if hasattr(response, 'parsed') and hasattr(response.parsed, 'fields'):
            print(f"  Parsed fields: {response.parsed.fields}")
    else:
        # This is a registered event
        if event == const.USER_DEFINED_EVENT:
            print(f"[{timestamp}] DEVICE EVENT: {device_id} → {event} (USER_DEFINED_EVENT)")
        else:
            print(f"[{timestamp}] DEVICE EVENT: {device_id} → {event}")


async def main():
    # Use "my-kaleidescape" on Windows
    kaleidescape = Kaleidescape("my-kaleidescape.local")
    
    # Connect event handlers
    kaleidescape.dispatcher.connect(const.SIGNAL_CONTROLLER_EVENT, controller_event_handler)
    kaleidescape.dispatcher.connect(const.SIGNAL_DEVICE_EVENT, device_event_handler)
    
    print("Connecting to Kaleidescape system...")
    print("Press Ctrl+C to stop monitoring events")
    print("-" * 50)
    
    try:
        # Connect with auto-reconnect enabled
        await kaleidescape.connect(auto_reconnect=True, reconnect_delay=5)
        
        # Get device information
        device = await kaleidescape.get_local_device()
        devices = await kaleidescape.get_devices()
        
        print(f"Connected to {len(devices)} device(s)")
        print(f"Local device: {device.device_id}")
        print(f"Current power state: {device.power.state}")
        print("-" * 50)
        
        # Keep the connection alive and monitor events
        # This will run indefinitely until interrupted
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n" + "-" * 50)
        print("Stopping event monitoring...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await kaleidescape.disconnect()
        print("Disconnected from Kaleidescape system")


if __name__ == "__main__":
    asyncio.run(main())