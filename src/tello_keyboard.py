from djitellopy import tello
import pygame
import logging
from dataclasses import dataclass
from typing import Tuple, Dict
import time
import numpy as np
import threading

@dataclass
class DroneConfig:
    """Configuration settings for drone control"""
    min_battery_level: int = 10
    speed_max: int = 250
    countersteer: int = 20
    speed_increase: int = 10
    speed_falloff: int = 5
    takeoff_cooldown: float = 3.0  # Seconds between takeoff/land commands

@dataclass
class ControlConfig:
    """Keyboard control mapping configuration"""
    movement_controls: Dict[str, Dict[str, str]] = None
    speed_controls: Dict[str, float] = None

    def __post_init__(self):
        if self.movement_controls is None:
            self.movement_controls = {
                'lr': {'pos': 'd', 'neg': 'a'},      # Left/Right
                'fb': {'pos': 'w', 'neg': 's'},      # Forward/Back
                'ud': {'pos': 'UP', 'neg': 'DOWN'},  # Up/Down
                'yv': {'pos': 'RIGHT', 'neg': 'LEFT'}# Yaw
            }
        if self.speed_controls is None:
            self.speed_controls = {
                'LSHIFT': 1.0,    # 100% speed
                'LCTRL': 0.5,     # 50% speed
                'default': 0.75   # 75% speed
            }

class DroneController:
    """Handles keyboard-based drone control"""
    def __init__(self, drone_config: DroneConfig = DroneConfig(),
                 control_config: ControlConfig = ControlConfig()):
        self.config = drone_config
        self.controls = control_config
        self.speeds = {'lr': 0, 'fb': 0, 'ud': 0, 'yv': 0}
        self._is_currently_flying = False  # Private variable for the property
        self.last_takeoff_time = 0
        self.logger = logging.getLogger(__name__)
        self.patrol_mode_active = False  # Flag for patrol mode

    @property
    def is_currently_flying(self) -> bool:
        """
        Property that returns whether the drone is currently in flight.
        Usage: status = drone_controller.is_currently_flying
        """
        return self._is_currently_flying

    @is_currently_flying.setter
    def is_currently_flying(self, value: bool):
        """
        Setter for the flight status.
        Usage: drone_controller.is_currently_flying = True
        """
        self._is_currently_flying = value

    def initialise_drone(self) -> tello.Tello:
        """
        Initialize and configure the drone.
        
        Returns:
            tello.Tello: Configured drone instance
            
        Raises:
            Exception: If battery level is too low or connection fails
        """
        try:
            drone = tello.Tello()
            drone.connect()

            battery = drone.get_battery()
            self.logger.info(f"Battery level: {battery}%")

            if battery < self.config.min_battery_level:
                raise Exception(f'Battery level too low: {battery}%')

            drone.LOGGER.setLevel(logging.WARNING)
            drone.streamon()
            
            # Sync our in_flight state with actual drone state
            self._is_currently_flying = False
            self.logger.info("Drone initialized successfully")
            return drone

        except Exception as e:
            self.logger.error(f"Failed to initialize drone: {e}")
            raise

    def get_key(self, key_name: str) -> bool:
        """Check if a specific key is pressed"""
        try:
            key_input = pygame.key.get_pressed()
            my_key = getattr(pygame, f'K_{key_name}')
            return key_input[my_key]
        except AttributeError:
            self.logger.warning(f"Invalid key name: {key_name}")
            return False

    def get_target_speed(self) -> int:
        """Calculate target speed based on modifier keys"""
        for key, multiplier in self.controls.speed_controls.items():
            if key != 'default' and self.get_key(key):
                return int(self.config.speed_max * multiplier)
        return int(self.config.speed_max * self.controls.speed_controls['default'])

    def apply_countersteer(self, speed: int, direction: str) -> int:
        """Apply countersteer to help stop movement"""
        if speed > 0:
            if speed > self.config.speed_falloff:
                return max(-self.config.countersteer, 
                    speed - self.config.speed_falloff)
            return 0
        elif speed < 0:
            if speed < -self.config.speed_falloff:
                return min(self.config.countersteer, 
                    speed + self.config.speed_falloff)
            return 0
        return 0

    def hover(self, drone: tello.Tello):
        """Hover in place without rotating."""
        try:
            drone.send_rc_control(0, 0, 0, 0)  # Hover in place
        except Exception as e:
            self.logger.error(f"Error during hover: {e}")

    def patrol_mode(self, drone: tello.Tello):
        """Enter patrol mode, rotating and scanning for faces."""
        self.patrol_mode_active = True
        self.logger.info("Patrol mode activated.")
        
        while self.patrol_mode_active and self.is_currently_flying:
            # Rotate slowly (adjust yaw)
            drone.send_rc_control(0, 0, 0, 20)  # Rotate right at a slow speed
            time.sleep(0.1)  # Adjust the sleep time for rotation speed

            # Check for face detection
            frame = drone.get_frame_read().frame
            frame, face_info = self.face_detector.find_face(frame)
            if face_info[1] != 0:  # If a face is detected
                self.lock_on_face(drone, face_info)

        self.logger.info("Patrol mode deactivated.")

    def lock_on_face(self, drone: tello.Tello, face_info):
        """Rotate to face the detected face."""
        try:
            x, _ = face_info[0]  # Get the x-coordinate of the face center
            frame_width = 1280  # Assuming your frame width is 1280

            # Calculate error from center
            error = x - (frame_width // 2)
            speed = int(np.clip(error * 0.1, -20, 20))  # Adjust speed based on error

            # Send control command to rotate towards the face
            drone.send_rc_control(0, 0, 0, speed)  # Adjust yaw based on error
        except Exception as e:
            self.logger.error(f"Error locking on to face: {e}")

    def update_controls(self, drone: tello.Tello) -> bool:
        """
        Update drone controls based on keyboard input.
        
        Returns:
            bool: True if any input was processed
        """
        try:
            # Add debug logging
            self.logger.debug("Starting update_controls")
            
            # Check if is_flying is callable
            if not hasattr(drone, 'is_flying'):
                self.logger.error("Drone object has no is_flying method")
                return False
                
            # Update flight status from drone
            try:
                # Make sure we're calling the method, not just referencing it
                if callable(drone.is_flying):
                    flying_status = drone.is_flying()
                else:
                    flying_status = drone.is_flying
                self.logger.debug(f"Current flying status: {flying_status}")
                self.is_currently_flying = bool(flying_status)  # Ensure boolean conversion
            except Exception as e:
                self.logger.error(f"Error checking flight status: {e}")
                return False

            had_input = False

            # Process movement controls
            for direction, keys in self.controls.movement_controls.items():
                if self.get_key(keys['pos']):
                    self.speeds[direction] = min(
                        self.speeds[direction] + self.config.speed_increase, 
                        self.get_target_speed()
                    )
                    had_input = True
                elif self.get_key(keys['neg']):
                    self.speeds[direction] = max(
                        self.speeds[direction] - self.config.speed_increase, 
                        -self.get_target_speed()
                    )
                    had_input = True
                else:
                    self.speeds[direction] = self.apply_countersteer(
                        self.speeds[direction], direction
                    )

            # Handle takeoff/landing
            current_time = time.time()
            cooldown_elapsed = (current_time - self.last_takeoff_time 
                              > self.config.takeoff_cooldown)

            if self.get_key("q") and self.is_currently_flying and cooldown_elapsed:
                drone.land()
                self.is_currently_flying = False
                had_input = True
                self.last_takeoff_time = current_time
            elif self.get_key("e") and not self.is_currently_flying and cooldown_elapsed:
                if not self.safe_takeoff(drone):
                    self.logger.error("Failed to take off after multiple attempts.")
                    return False

                # Start hovering after takeoff
                self.hover(drone)

                self.is_currently_flying = True
                had_input = True
                self.last_takeoff_time = current_time

            # Emergency stop
            if self.get_key("SPACE"):
                self.speeds = dict.fromkeys(self.speeds, 0)
                had_input = True

            # Start patrol mode in a separate thread
            if self.get_key("f") and self.is_currently_flying and not self.patrol_mode_active:
                patrol_thread = threading.Thread(target=self.patrol_mode, args=(drone,))
                patrol_thread.start()

            # Disable patrol mode
            if self.get_key("g") and self.patrol_mode_active:
                self.patrol_mode_active = False
                self.hover(drone)  # Optionally hover after exiting patrol mode

            # Send control commands to drone
            drone.send_rc_control(
                self.speeds['lr'], 
                self.speeds['fb'], 
                self.speeds['ud'], 
                self.speeds['yv']
            )

            return had_input

        except Exception as e:
            self.logger.error(f"Error updating controls: {e}", exc_info=True)
            return False

    def safe_takeoff(self, drone: tello.Tello) -> bool:
        """Safely take off the drone with retries."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                drone.takeoff()
                self.logger.info("Drone taking off...")
                time.sleep(5)  # Wait for a few seconds to stabilize
                self.is_currently_flying = True
                return True
            except Exception as e:
                self.logger.error(f"Takeoff attempt {attempt + 1} failed: {e}")
                time.sleep(2)  # Wait before retrying
        return False

# Create global instance
drone_controller = DroneController()
initialise_drone = drone_controller.initialise_drone
update_controls = drone_controller.update_controls 