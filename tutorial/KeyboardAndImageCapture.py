from djitellopy import tello
import KeyPress as kp
import time
import cv2
   
def getKeyboardInput(drone):
    lr, fb, ud, yv = 0, 0, 0, 0
    speed = 250
    if kp.getKey("LEFT"): yv -= speed
    if kp.getKey("RIGHT"): yv += speed
    if kp.getKey("UP"): ud += speed
    if kp.getKey("DOWN"): ud -= speed
    if kp.getKey("w"): fb += speed
    if kp.getKey("s"): fb -= speed
    if kp.getKey("a"): lr -= speed
    if kp.getKey("d"): lr += speed
    
    if kp.getKey("q"):
        drone.send_rc_control(0,0,0,0)
        drone.land()
        
    if kp.getKey("e"):
        drone.takeoff()
        
    if kp.getKey("z"):
        cv2.imwrite(f'Resources/Images/{time.time()}.jpg')
    
    return [lr, fb, ud, yv]

if __name__ == '__main__':
    kp.init()
    drone = tello.Tello()
    drone.connect()
    print(drone.get_battery())
    drone.streamon()
    
    while True:
        vals = getKeyboardInput(drone)
        drone.send_rc_control(vals[0], vals[1], vals[2], vals[3])
        img = drone.get_frame_read().frame
        #img = cv2.resize(img, (360,240))
        
        cv2.imshow("Image", img)
        #cv2.waitKey(1)
        

