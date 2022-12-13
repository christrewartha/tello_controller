from djitellopy import tello
import pygame
import cv2
import logging
import time

MINIMUM_BATTERY_LEVEL = 10
DRONE_SPEED_MAX = 250
DRONE_COUNTERSTEER = 20
DRONE_SPEED_INCREASE = 10
DRONE_SPEED_FALLOFF = 5
PYGAME_WINDOW_DIMENSONS = (800,600)

pygame_window = 0
take_snapshot = False
lr, fb, ud, yv = 0, 0, 0, 0
previous_error = 0

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


def initialise_pygame():
    pygame.init()
    global pygame_window
    pygame_window = pygame.display.set_mode(PYGAME_WINDOW_DIMENSONS)
    

def update_pygame():
    running = True
    pygame.display.update()
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif event.key == pygame.K_z:
                global take_snapshot
                take_snapshot = True
                
    return running


def quit_pygame():
    pygame.quit()    
    
    
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
    
    speed = DRONE_SPEED_MAX
    any_button_pressed = False
    
    if get_key("LEFT"):
        yv -= speed
        any_button_pressed = True
    if get_key("RIGHT"):
        yv += speed
        any_button_pressed = True
    if get_key("UP"):
        ud += speed
        any_button_pressed = True
    if get_key("DOWN"):
        ud -= speed
        any_button_pressed = True
    if get_key("w"):
        fb += speed
        any_button_pressed = True
    if get_key("s"):
        fb -= speed
        any_button_pressed = True
    if get_key("a"):
        lr -= speed
        any_button_pressed = True
    if get_key("d"):
        lr += speed
        any_button_pressed = True
    
    if get_key("q"):
        drone.land()
        any_button_pressed = True
        
    if get_key("e"):
        drone.takeoff()
        any_button_pressed = True
    
    drone.send_rc_control(lr, fb, ud, yv)
    
    return any_button_pressed


def drone_update_stream(drone, detect_face=False, track_face=False):
    
    # get the frame from the drone
    frame = drone.get_frame_read().frame
    
    global take_snapshot
    if take_snapshot:
        cv2.imwrite(f'Resources/Images/{time.time()}.jpg', frame)
        take_snapshot = False
    
    if detect_face:
        img, info = find_face(frame)
        if info[1] != 0:
            #found a face
            if track_face:
                global previous_error
                previous_error = trackFace(drone, info, 1280, previous_error)
        
    
    # convert format to blit to pygame surface
    frame = cv2.resize(frame, PYGAME_WINDOW_DIMENSONS)
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    frame = frame.swapaxes(0, 1)
    frame = cv2.flip(frame, 0)
    pygame.surfarray.blit_array(pygame_window, frame)
        
    
def find_face(img):
    xml_file = '../haar-cascade-files-master/haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(xml_file)
    
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(img_gray, 1.2, 8)
    
    faces_centres = []
    faces_areas = []
    
    for (x,y,w,h) in faces:
        cv2.rectangle(img,(x,y),(x+w, y+h), (0,0,255),2)
        cx = x + w // 2
        cy = y + h // 2
        area = w * h
        cv2.circle(img, (cx,cy), 5, (0,0,255), cv2.FILLED)
        faces_centres.append([cx, cy])
        faces_areas.append(area)
        
    if len(faces_areas) != 0:
        i = faces_areas.index(max(faces_areas))
        return img, [faces_centres[i], faces_areas[i]]
    else:
        return img, [[0,0],0]
    
    
def trackFace(drone, info, width, previous_error)
    fbRange = [6200, 6800]
    pid = [0.4, 0.4, 0]
    fb = 0
    
    x,y = info[0]
    area = info[1]
    
    error = x - width // 2
    speed = pid[0] * error + pid[1] * (error-previous_error)
    speed = int(np.clip(speed, -100, 100))
    
    if area > fbRange[0] and area < fbRange[1]:
        fb = 0
    elif area > fbRange[1]:
        fb = -20
    elif area < fbRange[0] and area != 0:
        fb = 20
        
    #send these values to the drone
        
    return error
    
