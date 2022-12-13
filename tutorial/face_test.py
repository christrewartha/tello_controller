import cv2
import numpy as np

def find_face(img):
    xml_file = '../../haar-cascade-files-master/haarcascade_frontalface_default.xml'
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
        cv2.circle(img, (cx,cy), 5, (0,255,0), cv2.FILLED)
        faces_centres.append([cx, cy])
        faces_areas.append(area)
        
    if len(faces_areas) != 0:
        i = faces_areas.index(max(faces_areas))
        return img, [faces_centres[i], faces_areas[i]]
    else:
        return img, [[0,0],0]


def trackFace(drone, info, w, pid, previous_error)
    fbRange = [6200, 6800]
    pid = [0.4, 0.4, 0]
    fb = 0
    
    x,y = info[0]
    area = info[1]
    
    error = x - w // 2
    speed = pid[0] * error + pid[1] * (error-previous_error)
    speed = int(np.clip(speed, -100, 100))
    
    if area > fbRange[0] and area < fbRange[1]:
        fb = 0
    elif area > fbRange[1]:
        fb = -20
    elif area < fbRange[0] and area != 0:
        fb = 20
    if x == 0:
        speed = 0
        error = 0
        
    #send these values to the drone
    return error

if __name__ == '__main__':
    cap = cv2.VideoCapture(0)
    while True:
        _, img = cap.read()
        img, info = find_face(img)
        print('Center', info[0], 'Area', info[1])
        cv2.imshow("Output", img)
        cv2.waitKey(1)
#        find_face(img)
        
        