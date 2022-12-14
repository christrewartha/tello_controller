from time import sleep
import sys

def run_tello():
    import tello_tools as tt
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
    sys.path.insert(0, '../../secret_config')
    from tello_secret import DRONE_NETWORK
    from tello_secret import WIFI_NETWORK
    
    import network_configurator as nc
    
    nc.join_network(DRONE_NETWORK)
    sleep(2)
    
    try:
        run_tello()
    finally:
        sleep(2)
        nc.join_network(WIFI_NETWORK)
    
    
    
    
    
    
