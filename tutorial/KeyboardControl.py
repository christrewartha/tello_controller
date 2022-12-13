from djitellopy import tello
import KeyPress as kp
from time import sleep



def getKeyboardInput():
    lr, fb, ud, yv = 0, 0, 0, 0
    speed = 200
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
    
    return [lr, fb, ud, yv]

if __name__ == '__main__':
    kp.init()
    drone = tello.Tello()
    drone.connect()
    print(drone.get_battery())
    
    while True:
        vals = getKeyboardInput()
        drone.send_rc_control(vals[0], vals[1], vals[2], vals[3])
        
