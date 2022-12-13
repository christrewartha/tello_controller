import network_configurator as nc
import tello_tools as tt
from time import sleep
import sys

def run_tello():
    
    # open connection to tello drone
    drone = tt.initialise_drone()
    
    # initialise pygame
    tt.initialise_pygame()
    # switch focus to pygame window

    # main loop
    running = True
    
    while running:
        running = tt.update_pygame()
        
        tt.drone_update_stream(drone)
        
        # update keyboard - movement based on this
        if tt.drone_wasd_controls(drone) == False:
            pass
        
        
        
        # detect faces
        # move based on the faces
        
        # recognise faces
        
        # detect surroundings
        # avoid surroundings
        

        # end main loop
        

    # close pygame
    tt.quit_pygame()


if __name__ == '__main__':
    
    # these are existing networks - no auth functionality
    DRONE_NETWORK = 'TELLO-5904FC'
    WIFI_NETWORK = 'BT- Jo'
    
    nc.join_network(DRONE_NETWORK)
    sleep(5)
    run_tello()
    
    nc.join_network(WIFI_NETWORK)
    
    
    
    
    
    