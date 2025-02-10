from djitellopy import tello
import pygame
import logging
import time

MINIMUM_BATTERY_LEVEL = 10
DRONE_SPEED_MAX = 250
DRONE_COUNTERSTEER = 20
DRONE_SPEED_INCREASE = 10
DRONE_SPEED_FALLOFF = 5

lr, fb, ud, yv = 0, 0, 0, 0
in_flight = False
last_qe_time = 0  # Tracks last time 'q' or 'e' was pressed
qe_delay_duration = 3.0

def initialise_drone():
    drone = tello.Tello()

    drone.connect()

    battery = drone.get_battery()
    print(drone.get_battery())

    if battery < MINIMUM_BATTERY_LEVEL:
        raise Exception('Battery level too low')

    drone.LOGGER.setLevel(logging.WARNING)
    drone.streamon()
    
    # Sync our in_flight state with actual drone state
    global in_flight
    in_flight = drone.is_flying()

    return drone


def get_key(key_name):
    ans = False

    key_input = pygame.key.get_pressed()
    my_key = getattr(pygame, 'K_{}'.format(key_name))
    if key_input[my_key]:
        ans = True
        
    return ans


def drone_wasd_controls(drone):
    global lr, fb, ud, yv, in_flight, last_qe_time
    
    # Update in_flight status from drone
    in_flight = drone.is_flying()

    # Track current speeds for each direction
    current_speed = {
        'lr': lr,
        'fb': fb,
        'ud': ud,
        'yv': yv
    }
    
    # Handle speed increase/decrease
    if get_key("LSHIFT"):  # Hold shift to go faster
        target_speed = DRONE_SPEED_MAX
    elif get_key("LCTRL"):  # Hold ctrl to go slower
        target_speed = DRONE_SPEED_MAX // 2
    else:
        target_speed = DRONE_SPEED_MAX * 0.75  # Default to 75% speed

    # Movement controls with smooth acceleration
    controls = {
        'lr': {'pos': 'd', 'neg': 'a'},
        'fb': {'pos': 'w', 'neg': 's'},
        'ud': {'pos': 'UP', 'neg': 'DOWN'},
        'yv': {'pos': 'RIGHT', 'neg': 'LEFT'}
    }

    any_input = False
    
    # Process each movement direction
    for direction, keys in controls.items():
        if get_key(keys['pos']):
            current_speed[direction] = min(current_speed[direction] + DRONE_SPEED_INCREASE, target_speed)
            any_input = True
        elif get_key(keys['neg']):
            current_speed[direction] = max(current_speed[direction] - DRONE_SPEED_INCREASE, -target_speed)
            any_input = True
        else:
            # Apply smooth deceleration with countersteer
            if current_speed[direction] > 0:
                if current_speed[direction] > DRONE_SPEED_FALLOFF:
                    # Apply countersteer when speed is significant
                    current_speed[direction] = max(-DRONE_COUNTERSTEER, 
                        current_speed[direction] - DRONE_SPEED_FALLOFF)
                else:
                    # Return to zero when speed is low
                    current_speed[direction] = 0
            elif current_speed[direction] < 0:
                if current_speed[direction] < -DRONE_SPEED_FALLOFF:
                    # Apply countersteer when speed is significant
                    current_speed[direction] = min(DRONE_COUNTERSTEER, 
                        current_speed[direction] + DRONE_SPEED_FALLOFF)
                else:
                    # Return to zero when speed is low
                    current_speed[direction] = 0

    # Update global variables
    lr, fb, ud, yv = current_speed['lr'], current_speed['fb'], current_speed['ud'], current_speed['yv']

    # Handle takeoff/landing
    current_time = time.time()
    if get_key("q") and in_flight and (current_time - last_qe_time > qe_delay_duration):
        drone.land()
        in_flight = False
        any_input = True
        last_qe_time = current_time
    elif get_key("e") and not in_flight and (current_time - last_qe_time > qe_delay_duration):
        drone.takeoff()
        in_flight = True
        any_input = True
        last_qe_time = current_time

    # Emergency stop (space bar)
    if get_key("SPACE"):
        lr, fb, ud, yv = 0, 0, 0, 0
        any_input = True

    drone.send_rc_control(lr, fb, ud, yv)
    return any_input

