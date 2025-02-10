import numpy as np
import cv2
import time
import tello_pygame
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple, List, Optional
import logging

# Configuration
@dataclass
class FaceTrackConfig:
    fb_range: Tuple[int, int] = (6200, 6800)
    pid: Tuple[float, float, float] = (0.4, 0.4, 0)
    scale_factor: float = 1.2
    min_neighbors: int = 8
    max_speed: int = 100
    min_face_size: Tuple[int, int] = (30, 30)
    max_face_size: Tuple[int, int] = (0, 0)  # (0,0) means no maximum

@dataclass
class VideoConfig:
    cascade_path: Path = Path('data/haarcascades/haarcascade_frontalface_default.xml')
    snapshot_dir: Path = Path('../Resources/Images')
    frame_width: int = 1280
    frame_height: int = 720
    fps_limit: int = 30

class TrackingMovement:
    """Handles drone movement based on tracking data"""
    def __init__(self, config: FaceTrackConfig = FaceTrackConfig()):
        self.config = config
        self.previous_error = 0
        self.last_movement_time = time.time()
        self.movement_timeout = 0.1  # 100ms minimum between movements

    def track_face(self, drone, info, width) -> Tuple[int, dict]:
        """
        Calculate and apply control values for tracking a detected face.
        
        Args:
            drone: Tello drone instance
            info: Face detection info [center_coordinates, area]
            width: Frame width
            
        Returns:
            Tuple[int, dict]: Current tracking error and movement stats
        """
        current_time = time.time()
        if current_time - self.last_movement_time < self.movement_timeout:
            return self.previous_error, {}

        fb = 0
        x, _ = info[0]
        area = info[1]

        # Calculate PID control
        error = x - width // 2
        speed = (self.config.pid[0] * error + 
                self.config.pid[1] * (error - self.previous_error))
        speed = int(np.clip(speed, -self.config.max_speed, 
                           self.config.max_speed))

        # Calculate forward/backward movement
        if self.config.fb_range[0] < area < self.config.fb_range[1]:
            fb = 0
        elif area > self.config.fb_range[1]:
            fb = -20
        elif area < self.config.fb_range[0] and area != 0:
            fb = 20

        movement_stats = {
            'error': error,
            'speed': speed,
            'fb': fb,
            'area': area
        }

        if area != 0:
            try:
                drone.send_rc_control(0, fb, 0, speed)
                self.last_movement_time = current_time
            except Exception as e:
                logging.error(f"Failed to send movement command: {e}")
        
        self.previous_error = error
        return error, movement_stats


class FaceDetector:
    """Handles face detection in video frames"""
    def __init__(self, face_config: FaceTrackConfig = FaceTrackConfig(), 
                 video_config: VideoConfig = VideoConfig()):
        self.config = face_config
        try:
            if not Path(video_config.cascade_path).exists():
                raise FileNotFoundError(f"Cascade file not found: {video_config.cascade_path}")
            
            self.face_cascade = cv2.CascadeClassifier(str(video_config.cascade_path))
            if self.face_cascade.empty():
                raise Exception(f"Failed to load cascade classifier")
        except Exception as e:
            logging.error(f"Face detector initialization failed: {e}")
            raise

    def find_face(self, img) -> Tuple[np.ndarray, List]:
        """
        Detect faces in the image and return the largest face's position and area.
        
        Args:
            img: Input image in BGR format
            
        Returns:
            tuple: (processed_image, [center_coordinates, area])
        """
        try:
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(
                img_gray, 
                self.config.scale_factor, 
                self.config.min_neighbors,
                minSize=self.config.min_face_size,
                maxSize=self.config.max_face_size if any(self.config.max_face_size) else None
            )

            faces_centres = []
            faces_areas = []

            for (x, y, w, h) in faces:
                cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 2)
                cx = x + w // 2
                cy = y + h // 2
                area = w * h
                cv2.circle(img, (cx, cy), 5, (0, 0, 255), cv2.FILLED)
                faces_centres.append([cx, cy])
                faces_areas.append(area)

            if faces_areas:
                i = faces_areas.index(max(faces_areas))
                return img, [faces_centres[i], faces_areas[i]]
            return img, [[0, 0], 0]
        except Exception as e:
            logging.error(f"Face detection failed: {e}")
            return img, [[0, 0], 0]


class VideoManager:
    """Manages video stream processing and snapshot functionality"""
    def __init__(self, video_config: VideoConfig = VideoConfig()):
        self.config = video_config
        self.face_detector = FaceDetector()
        self.tracking_movement = TrackingMovement()
        self.take_snapshot = False
        self.frame_count = 0
        self.last_frame_time = time.time()
        self.fps = 0
        
        self.config.snapshot_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO)

    def calculate_fps(self):
        """Calculate and update FPS"""
        current_time = time.time()
        self.frame_count += 1
        if current_time - self.last_frame_time >= 1.0:
            self.fps = self.frame_count
            self.frame_count = 0
            self.last_frame_time = current_time
        return self.fps

    def take_a_snapshot(self):
        """Trigger snapshot on next frame"""
        self.take_snapshot = True

    def save_snapshot(self, frame) -> Optional[Path]:
        """
        Save frame with timestamp and sequential numbering
        Returns: Path to saved file or None if save failed
        """
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            existing_files = len(list(self.config.snapshot_dir.glob(f"{timestamp}_*.jpg")))
            filename = self.config.snapshot_dir / f"{timestamp}_{existing_files + 1}.jpg"
            cv2.imwrite(str(filename), frame)
            logging.info(f"Snapshot saved: {filename}")
            return filename
        except Exception as e:
            logging.error(f"Failed to save snapshot: {e}")
            return None
        finally:
            self.take_snapshot = False

    def update_stream(self, drone, detect_face=False, track_face=False) -> dict:
        """
        Update video stream and process frame based on settings.
        
        Returns:
            dict: Status information including FPS and tracking stats
        """
        status = {'fps': self.calculate_fps(), 'tracking_stats': None}
        
        try:
            frame = drone.get_frame_read().frame
            
            # Get pygame window dimensions
            pygame_dims = tello_pygame.get_dimensions()
            
            # Resize frame to match pygame window exactly
            frame = cv2.resize(frame, pygame_dims)

            if self.take_snapshot:
                saved_path = self.save_snapshot(frame)
                status['snapshot_saved'] = saved_path

            if detect_face:
                frame, info = self.face_detector.find_face(frame)
                if info[1] != 0 and track_face:
                    _, tracking_stats = self.tracking_movement.track_face(
                        drone, info, pygame_dims[0])  # Use width from pygame dimensions
                    status['tracking_stats'] = tracking_stats

            # Convert format for pygame display
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = frame.swapaxes(0, 1)
            frame = cv2.flip(frame, 0)
            
            # Ensure frame matches pygame surface dimensions exactly
            if frame.shape[:2] == pygame_dims:  # Check dimensions before blitting
                tello_pygame.blit_frame(frame)
            else:
                logging.warning(f"Frame dimensions {frame.shape[:2]} don't match pygame surface {pygame_dims}")

            return status
        except Exception as e:
            logging.error(f"Stream update failed: {e}")
            return status


# Create global instance
video_manager = VideoManager()
take_a_snapshot = video_manager.take_a_snapshot
drone_update_stream = video_manager.update_stream
