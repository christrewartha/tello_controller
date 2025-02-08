from djitellopy import tello
import pygame
import numpy as np
import cv2
import logging
import time

MINIMUM_BATTERY_LEVEL = 10
DRONE_SPEED_MAX = 250
DRONE_COUNTERSTEER = 20
DRONE_SPEED_INCREASE = 10
DRONE_SPEED_FALLOFF = 5

lr, fb, ud, yv = 0, 0, 0, 0
previous_error = 0
in_flight = False

def initialise_drone():

    drone = tello.Tello()

    drone.connect()
   
    battery = drone.get_battery()
    print(drone.get_battery())

    if battery < MINIMUM_BATTERY_LEVEL:
        raise Exception('Battery level too low')

    drone.LOGGER.setLevel(logging.WARNING)
    drone.streamon()

    return drone


def get_key(key_name):
    ans = False

    key_input = pygame.key.get_pressed()
    my_key = getattr(pygame, 'K_{}'.format(key_name))
    if key_input[my_key]:
        ans = True
        
    return ans


def drone_wasd_controls(drone):
    
    global lr
    global fb
    global ud
    global yv
    global in_flight

    qe_pressed = False
    yv_pressed = False
    ud_pressed = False
    fb_pressed = False
    lr_pressed = False

    speed = DRONE_SPEED_MAX

    if get_key("LEFT"):
        yv -= speed
        yv_pressed = True
    if get_key("RIGHT"):
        yv += speed
        yv_pressed = True

    if not yv_pressed:
        yv = 0

    if get_key("UP"):
        ud += speed
        ud_pressed = True
    if get_key("DOWN"):
        ud -= speed
        ud_pressed = True

    if not ud_pressed:
        ud = 0

    if get_key("w"):
        fb += speed
        fb_pressed = True
    if get_key("s"):
        fb -= speed
        fb_pressed = True

    if not fb_pressed:
        fb = 0

    if get_key("a"):
        lr -= speed
        lr_pressed = True
    if get_key("d"):
        lr += speed
        lr_pressed = True

    if not lr_pressed:
        lr = 0

    if get_key("q") and in_flight:
        drone.land()
        qe_pressed = True
        
    if get_key("e"):
        drone.takeoff()
        in_flight = True
        qe_pressed = True

    drone.send_rc_control(lr, fb, ud, yv)
    
    return ud_pressed or fb_pressed or lr_pressed or yv_pressed or qe_pressed



def find_face(img):
    xml_file = '../../haar-cascade-files-master/haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(xml_file)

    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(img_gray, 1.2, 8)

    faces_centres = []
    faces_areas = []

    for (x, y, w, h) in faces:
        cv2.rectangle(img, (x, y), (x+w, y+h), (0, 0, 255), 2)
        cx = x + w // 2
        cy = y + h // 2
        area = w * h
        cv2.circle(img, (cx, cy), 5, (0, 0, 255), cv2.FILLED)
        faces_centres.append([cx, cy])
        faces_areas.append(area)

    if len(faces_areas) != 0:
        i = faces_areas.index(max(faces_areas))
        return img, [faces_centres[i], faces_areas[i]]
    else:
        return img, [[0, 0], 0]


def trackFace(drone, info, width, previous_error):
    fb_range = [6200, 6800]
    pid = [0.4, 0.4, 0]
    fb = 0

    x,y = info[0]
    area = info[1]

    error = x - width // 2
    speed = pid[0] * error + pid[1] * (error-previous_error)
    speed = int(np.clip(speed, -100, 100))

    if fb_range[0] < area < fb_range[1]:
        fb = 0
    elif area > fb_range[1]:
        fb = -20
    elif area < fb_range[0] and area != 0:
        fb = 20

    # send these values to the drone

    return error

