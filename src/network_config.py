import platform
import subprocess
import os
from time import sleep

previous_network = None


# check in a list of strings for the substring "TELLO", return the index if found
def find_tello_network(network_list):
    for i, network in enumerate(network_list):
        if "TELLO" in network:
            return i
    return -1



def configure_network_for_tello():
    global previous_network
    previous_network = get_current_wifi_network()

    print("Scanning available Wi-Fi networks:\n")
    networks = os.popen('netsh wlan show networks').read().splitlines()
    network_list = [line.split(':')[1].strip() for line in networks if 'SSID' in line]

    for i, network in enumerate(network_list):
        print(f"{i + 1}. {network}")

    print(f"0. Exit Application")

    connection_index = int(input("\nSelect a network to connect to (enter the number): ")) - 1
    if connection_index == -1:
        print("Exiting.")
        exit()

    if 0 <= connection_index < len(network_list):
        print(f"Connecting to {network_list[connection_index]}")
    else:
        print("Invalid selection. Exiting.")
        exit()

    selected_network = network_list[connection_index]
    join_network(selected_network)
    print("Connected to network.")
    sleep(2)


def restore_network_configuration():
    global previous_network
    if previous_network is not None:
        join_network(previous_network)
        print("Restored previous network configuration.")
    else:
        print("No previous network configuration found.")


def get_current_wifi_network():
    out = subprocess.check_output('netsh wlan show interfaces').decode("utf-8")
    current = out.split("\n")[9].split(": ")[1]
    print(f"Current WiFi Network: {current}")
    return current


def display_available_networks():

    if platform.system() == "Windows":
        command = "netsh wlan show networks interface=WiFi"
        p = subprocess.Popen(command, shell=True)
        p.wait()
    elif platform.system() == "Linux":
        command = "nmcli dev wifi"
        os.system(command)

    else:
        raise Exception('Unsupported platform')
    
    
def join_network(network):
    disconnect_command = "netsh wlan disconnect"
    connect_command = f'netsh wlan connect name="{network}"'

    if platform.system() == "Windows":
        disconnect_command = "netsh wlan disconnect"
        connect_command = f'netsh wlan connect name="{network}"'

        p = subprocess.Popen(disconnect_command, shell=True)
        p.wait()

        p = subprocess.Popen(connect_command, shell=True)
        p.wait()
    elif platform.system() == "Linux":
        disconnect_command = "nmcli device disconnect wlan0"
        connect_command = f'nmcli dev wifi connect "{network}"'
        os.system(disconnect_command)

        os.system(connect_command)

    else:
        raise Exception('Unsupported platform')


