import network_config
import tello_keyboard
import tello_pygame
import tello_video

def run_tello():

    # open connection to tello drone
    drone = tello_keyboard.initialise_drone()
    
    # initialise videomanager
    video_manager = tello_video.VideoManager


    # initialise pygame
    tello_pygame.initialise_pygame()
    # switch focus to pygame window

    # main loop
    running = True
    
    while running:
        running = tello_pygame.update_pygame()
        
        tello_video.drone_update_stream(drone)  
        
        # update keyboard - movement based on this
        if not tello_keyboard.update_controls(drone):
            pass


        # detect faces
        # move based on the faces
        
        # recognise faces
        
        # detect surroundings
        # avoid surroundings

        # end main loop

    # close pygame
    tello_pygame.quit_pygame()


# this function returns the name of the current wifi network

if __name__ == '__main__':

    print(network_config.get_current_wifi_network())

    network_config.configure_network_for_tello()

    run_tello()

    network_config.restore_network_configuration()

    
    
    
    
    
