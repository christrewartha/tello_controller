import platform
import subprocess
import os


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
