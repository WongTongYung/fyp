import cv2 as cv
import sys
from ultralytics import YOLO

scale_down = 0.5

def image_read(img): 
    img_resize = cv.resize(img, (1500, 800), fx=scale_down, fy=scale_down, interpolation=cv.INTER_LINEAR)
    return img_resize
    
