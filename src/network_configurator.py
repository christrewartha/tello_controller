import platform
import subprocess



def display_available_networks():
    if platform.system() == "Windows":
        command = "netsh wlan show networks interface=WiFi"
        p = subprocess.Popen(command, shell=True)
        p.wait()
    else:
        raise Exception('Unsupported platform')
    
    
def join_network(network):
    if platform.system() == "Windows":
        command = "netsh wlan disconnect"
        p = subprocess.Popen(command, shell=True)
        p.wait()
        
        command = f'netsh wlan connect name="{network}"'
        p = subprocess.Popen(command, shell=True)
        p.wait()
    else:
        raise Exception('Unsupported platform')
