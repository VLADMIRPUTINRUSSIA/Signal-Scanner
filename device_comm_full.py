import os
import sys
import time
import json
import logging
import schedule
import bluetooth
import subprocess
import asyncio
from datetime import datetime
from pywifi import PyWiFi
from bleak import BleakScanner

# Logging Setup
BASE_DIR = os.path.expanduser("~/.scanner_logs")
os.makedirs(BASE_DIR, exist_ok=True)
logging.basicConfig(filename='debug.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def timestamp():
    return datetime.utcnow().isoformat()


def write_json(data, subdir, prefix):
    folder = os.path.join(BASE_DIR, subdir)
    os.makedirs(folder, exist_ok=True)
    filename = os.path.join(folder, f"{prefix}_{timestamp().replace(':', '-')}.json")
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
        logging.info(f"Saved to {filename}")
    except Exception as e:
        logging.error(f"JSON write error: {e}")


def scan_wifi():
    wifi = PyWiFi()
    iface = wifi.interfaces()[0]
    iface.scan()
    time.sleep(5)
    results = iface.scan_results()
    data = []
    for net in results:
        data.append({
            "SSID": net.ssid,
            "BSSID": net.bssid,
            "Signal": net.signal,
            "Frequency": net.freq,
            "Timestamp": timestamp()
        })
    write_json(data, 'wifi_scans', 'wifi')
    return data


def scan_bluetooth_classic():
    try:
        devices = bluetooth.discover_devices(duration=8, lookup_names=True, flush_cache=True)
        data = [{
            "Address": addr,
            "Name": name,
            "Type": "Classic",
            "Timestamp": timestamp()
        } for addr, name in devices]
        write_json(data, 'bt_scans', 'classic')
        return data
    except Exception as e:
        logging.error(f"Bluetooth Classic scan error: {e}")
        return []


async def scan_bluetooth_ble():
    try:
        devices = await BleakScanner.discover(timeout=8.0)
        data = [{
            "Address": d.address,
            "Name": d.name or "Unknown",
            "RSSI": d.rssi,
            "Type": "BLE",
            "Timestamp": timestamp()
        } for d in devices]
        write_json(data, 'bt_scans', 'ble')
        return data
    except Exception as e:
        logging.error(f"BLE scan error: {e}")
        return []


def communicate_bluetooth(addr):
    try:
        print(f"[+] Connecting to {addr} via RFCOMM...")
        sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        sock.connect((addr, 1))
        msg = "Hello Bluetooth Device!\n"
        sock.send(msg)
        print(f"[>] Sent: {msg.strip()}")
        response = sock.recv(1024).decode('utf-8', errors='ignore')
        print(f"[<] Received: {response}")
        sock.close()
        return {"to": addr, "sent": msg.strip(), "received": response.strip(), "time": timestamp()}
    except Exception as e:
        logging.error(f"Bluetooth comm error: {e}")
        return None


def communicate_wifi(bssid_or_ip):
    try:
        print(f"[+] Pinging {bssid_or_ip}...")
        result = subprocess.run(["ping", "-c", "2", bssid_or_ip],
                                capture_output=True, text=True)
        success = result.returncode == 0
        return {
            "target": bssid_or_ip,
            "status": "reachable" if success else "unreachable",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "time": timestamp()
        }
    except Exception as e:
        logging.error(f"Wi-Fi ping error: {e}")
        return None


def auto_communicate(bt_classic, wifi_list):
    bt_results = []
    for device in bt_classic:
        result = communicate_bluetooth(device['Address'])
        if result:
            bt_results.append(result)
    write_json(bt_results, "comm_logs", "bt_comm")

    wifi_results = []
    for ap in wifi_list:
        if ap["BSSID"]:
            result = communicate_wifi(ap["BSSID"])
            if result:
                wifi_results.append(result)
    write_json(wifi_results, "comm_logs", "wifi_comm")


def interactive_terminal(bt_classic, wifi_list):
    print("\n[MANUAL CONTROL]")
    print("1. Talk to Bluetooth Device")
    print("2. Ping Wi-Fi BSSID/IP")
    print("3. Exit")
    choice = input(">> Choose: ")
    if choice == "1":
        for i, dev in enumerate(bt_classic):
            print(f"{i+1}. {dev['Name']} - {dev['Address']}")
        sel = int(input("Select device #: ")) - 1
        communicate_bluetooth(bt_classic[sel]['Address'])
    elif choice == "2":
        for i, net in enumerate(wifi_list):
            print(f"{i+1}. {net['SSID']} - {net['BSSID']}")
        sel = int(input("Select Wi-Fi #: ")) - 1
        communicate_wifi(wifi_list[sel]['BSSID'])
    else:
        print("Exiting manual mode.")


def scan_and_communicate(interactive=False):
    logging.info("Starting full scan & communication cycle")
    wifi_list = scan_wifi()
    bt_classic = scan_bluetooth_classic()
    asyncio.run(scan_bluetooth_ble())
    auto_communicate(bt_classic, wifi_list)
    if interactive:
        interactive_terminal(bt_classic, wifi_list)


def hourly_scheduler():
    schedule.every(1).hours.do(scan_and_communicate)
    logging.info("Hourly auto-scan running. Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(1)


def main():
    if "--once" in sys.argv:
        scan_and_communicate()
    elif "--manual" in sys.argv:
        scan_and_communicate(interactive=True)
    elif "--hourly" in sys.argv:
        hourly_scheduler()
    else:
        print("""
Linux Device Communicator v2
Usage:
  python3 device_comm_full.py --once      # Run one scan and try to communicate
  python3 device_comm_full.py --manual    # Run + manual target selection
  python3 device_comm_full.py --hourly    # Continuous scanning every hour
  Output: ~/.scanner_logs + debug.log
        """)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted.")
    except Exception as e:
        logging.critical(f"Fatal error: {e}")
