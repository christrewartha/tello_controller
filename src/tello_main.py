import network_configurator as network_config
import tello_controls as controls

def run_tello():

    # open connection to tello drone
    drone = controls.initialise_drone()
    
    # initialise pygame
    controls.initialise_pygame()
    # switch focus to pygame window

    # main loop
    running = True
    
    while running:
        running = controls.update_pygame()
        
        controls.drone_update_stream(drone)
        
        # update keyboard - movement based on this
        if not controls.drone_wasd_controls(drone):
            pass

        # detect faces
        # move based on the faces
        
        # recognise faces
        
        # detect surroundings
        # avoid surroundings

        # end main loop

    # close pygame
    controls.quit_pygame()


# this function returns the name of the current wifi network

if __name__ == '__main__':

    #network_config.configure_network_for_tello()

    run_tello()

    #network_config.restore_network_configuration()

    
    
    
    
    
