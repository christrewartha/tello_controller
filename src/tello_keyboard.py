from djitellopy import tello
import pygame
import logging
from dataclasses import dataclass, field
from typing import Tuple, Dict
import time
import numpy as np
import threading
import tello_video

@dataclass
class DroneConfig:
    """Configuration settings for drone control"""
    min_battery_level: int = 10
    speed_max: int = 100
    countersteer: int = 20
    speed_increase: int = 10  # Maximum speed increase per key press
    speed_falloff: int = 5
    takeoff_cooldown: float = 3.0  # Seconds between takeoff/land commands
    patrol_rotation_speed: int = 25
    patrol_tracking_speed: int = 25
    max_speed: int = 100  # Maximum speed for movement
    acceleration_rate: int = 3  # Speed increase per update

@dataclass
class ControlConfig:
    """Keyboard control mapping configuration"""
    movement_controls: Dict[str, Dict[str, str]] = field(default_factory=lambda: {
        'lr': {'pos': 'd', 'neg': 'a'},      # Left/Right
        'fb': {'pos': 'w', 'neg': 's'},      # Forward/Back
        'ud': {'pos': 'UP', 'neg': 'DOWN'},  # Up/Down
        'yv': {'pos': 'RIGHT', 'neg': 'LEFT'} # Yaw
    })
    speed_controls: Dict[str, float] = field(default_factory=lambda: {
        'LSHIFT': 1.0,    # 100% speed
        'LCTRL': 1.0,     # 50% speed
        'default': 1.0   # 75% speed
    })
    state_controls: Dict[str, str] = field(default_factory=lambda: {
        'takeoff': 'e',   # Key to take off
        'land': 'q',      # Key to land
        'patrol': 'f',    # Key to enter patrol mode
        'stop_patrol': 'g', # Key to stop patrol mode
        'flip_left': 'j', # Key to flip left
        'flip_right': 'l',
        'flip_forward': 'i',
        'flip_back': 'k'
    })

@dataclass
class AlternativeConfig:
    """Keyboard control mapping configuration"""
    movement_controls: Dict[str, Dict[str, str]] = field(default_factory=lambda: {
        'lr': {'pos': 'd', 'neg': 'a'},      # Left/Right
        'fb': {'pos': 'w', 'neg': 's'},      # Forward/Back
        'ud': {'pos': 'UP', 'neg': 'DOWN'},  # Up/Down
        'yv': {'pos': 'RIGHT', 'neg': 'LEFT'} # Yaw
    })
    speed_controls: Dict[str, float] = field(default_factory=lambda: {
        'LSHIFT': 1.0,    # 100% speed
        'LCTRL': 1.0,     # 50% speed
        'default': 1.0   # 75% speed
    })
    state_controls: Dict[str, str] = field(default_factory=lambda: {
        'takeoff': 'e',   # Key to take off
        'land': 'q',      # Key to land
        'patrol': 'f',    # Key to enter patrol mode
        'stop_patrol': 'g', # Key to stop patrol mode
        'flip_left': 'j', # Key to flip left
        'flip_right': 'l',
        'flip_forward': 'i',
        'flip_back': 'k'
    })


class Command:
    """Represents a single command for the drone."""
    def __init__(self, action: str, params: dict, duration: float):
        self.action = action
        self.params = params
        self.duration = duration

# patrol script
patrol_script = [
    Command("fb", {"speed": 50}, 1),
    Command("fb", {"speed": -50}, 1),
]

class DroneController:
    """Handles keyboard-based drone control"""
    def __init__(self, drone_config: DroneConfig = DroneConfig(),
                 control_config: ControlConfig = ControlConfig()):
        self.config = drone_config
        self.controls = control_config
        self.speeds = {'lr': 0, 'fb': 0, 'ud': 0, 'yv': 0}
        self.current_speeds = {'lr': 0, 'fb': 0, 'ud': 0, 'yv': 0}  # Track current speeds
        self._is_currently_flying = False  # Private variable for the property
        self.last_takeoff_time = 0
        self.logger = logging.getLogger(__name__)
        self.patrol_mode_active = False  # Flag for patrol mode
        self.patrol_tracking_active = False
        self.frames_since_last_detection = 0  # Counter for frames since last face detection
        self.max_frames_without_detection = 10  # Number of frames to continue tracking
        self.patrol_commands = []
        self.current_command_index = 0
        self.current_command_start_time = 0
        for command in patrol_script:
            self.add_command(command.action, command.params, command.duration)

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
        
    def patrol(self, drone: tello.Tello):
        # Rotate slowly (adjust yaw)
        drone.send_rc_control(0, 0, 0, self.config.patrol_rotation_speed)  # Rotate right at a slow speed

        # Check for face detection
        
        frame = drone.get_frame_read().frame
        frame, face_info = tello_video.detect_face(frame)
        if face_info[1] != 0:  # If a face is detected
            self.logger.info("Face detected.")
            self.lock_on_face(drone, face_info)

        self.logger.info("Patrol mode deactivated.")

    def process_face_tracking(self, drone: tello.Tello, face_info):
        """Process face tracking logic while maintaining a set distance."""
        x, y, width, height = face_info[0]  # Get the coordinates and size of the face
        frame_width = 1280  # Assuming your frame width is 1280
        frame_height = 720  # Assuming your frame height is 720

        # Calculate error from center
        error_x = x - (frame_width // 2)
        speed_x = int(np.clip(error_x * 0.1, -20, 20))  # Adjust yaw based on x error

        # Set desired distance and calculate current distance based on face size
        desired_distance = 100  # Set your desired distance in cm
        current_distance = (desired_distance * frame_height) / height  # Estimate distance based on face height
        distance_error = current_distance - desired_distance
        speed_y = int(np.clip(distance_error * 0.1, -20, 20))  # Adjust altitude based on distance error

        # Send control commands to rotate towards the face and maintain altitude
        drone.send_rc_control(0, speed_y, 0, speed_x)  # Adjust up/down and yaw based on errors

    def track(self, drone: tello.Tello):
        """Rotate to face the detected face."""
        try:
            # Check for face detection
            frame = drone.get_frame_read().frame
            frame, face_info = self.face_detector.find_face(frame)
            if face_info[1] != 0:  # If a face is detected
                last_face_info = face_info
                self.frames_since_last_detection = 0
                self.process_face_tracking(drone, face_info)  # Call the new method
            else:
                self.frames_since_last_detection += 1
                if self.frames_since_last_detection <= self.max_frames_without_detection and last_face_info is not None:
                    self.process_face_tracking(drone, last_face_info)  # Continue tracking the last known face
                else:
                    self.logger.info("No face detected.")
                    drone.send_rc_control(0, 0, 0, 0)  # Stop rotating if no face is detected

        except Exception as e:
            self.logger.error(f"Error locking on to face: {e}")

    def lock_on_face(self, drone: tello.Tello, face_info):
        """Enter patrol mode, rotating and scanning for faces."""
        self.patrol_tracking_active = True
        self.logger.info("Tracking mode activated.")

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

            # Check for takeoff
            if self.get_key(self.controls.state_controls['takeoff']) and not self.is_currently_flying:
                if not self.safe_takeoff(drone):
                    self.logger.error("Failed to take off after multiple attempts.")
                    return False

                # Start hovering after takeoff
                self.hover(drone)

            # Check for patrol mode activation
            if self.get_key(self.controls.state_controls['patrol']) and self.is_currently_flying and not self.patrol_mode_active:
                self.patrol_mode_active = True

            # Check for patrol mode deactivation
            if self.get_key(self.controls.state_controls['stop_patrol']) and self.patrol_mode_active:
                self.patrol_mode_active = False
                #self.hover(drone)  # Optionally hover after exiting patrol mode

            # Check for flip
            if self.get_key(self.controls.state_controls['flip_left']) and self.is_currently_flying:
                drone.flip_left()
            elif self.get_key(self.controls.state_controls['flip_right']) and self.is_currently_flying:
                drone.flip_right()
            elif self.get_key(self.controls.state_controls['flip_forward']) and self.is_currently_flying:
                drone.flip_forward()
            elif self.get_key(self.controls.state_controls['flip_back']) and self.is_currently_flying:
                drone.flip_back()

            # Process movement controls
            for direction, keys in self.controls.movement_controls.items():
                if self.get_key(keys['pos']):
                    # Increase speed gradually
                    if self.current_speeds[direction] < self.config.max_speed:
                        self.current_speeds[direction] += self.config.acceleration_rate
                        self.current_speeds[direction] = min(self.current_speeds[direction], self.config.max_speed)
                    self.speeds[direction] = self.current_speeds[direction]
                elif self.get_key(keys['neg']):
                    # Decrease speed gradually
                    if self.current_speeds[direction] > -self.config.max_speed:
                        self.current_speeds[direction] -= self.config.acceleration_rate
                        self.current_speeds[direction] = max(self.current_speeds[direction], -self.config.max_speed)
                    self.speeds[direction] = self.current_speeds[direction]
                else:
                    # Apply countersteer if no key is pressed
                    self.speeds[direction] = self.apply_countersteer(
                        self.speeds[direction], direction
                    )
                    # Gradually decrease speed when key is released
                    if self.current_speeds[direction] > 0:
                        self.current_speeds[direction] = max(0, self.current_speeds[direction] - self.config.speed_falloff)
                    elif self.current_speeds[direction] < 0:
                        self.current_speeds[direction] = min(0, self.current_speeds[direction] + self.config.speed_falloff)

            # Emergency stop
            if self.get_key("SPACE"):
                self.speeds = dict.fromkeys(self.speeds, 0)
                self.current_speeds = dict.fromkeys(self.current_speeds, 0)

            # Start tracking mode
            if self.patrol_tracking_active:
                self.track(drone)
            elif self.patrol_mode_active:
                self.execute_patrol_script(drone)
                #self.patrol(drone)

            # Send control commands to drone
            drone.send_rc_control(
                self.speeds['lr'], 
                self.speeds['fb'], 
                self.speeds['ud'], 
                self.speeds['yv']
            )

            return True  # Indicate that controls were updated

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

    def add_command(self, action: str, params: dict, duration: float):
        """Add a command to the script."""
        command = Command(action, params, duration)
        self.patrol_commands.append(command)

    def start_patrol_script(self):
        """Start the sequence of commands."""
        self.current_command_index = 0
        self.current_command_start_time = time.time()

    def execute_patrol_script(self, drone: tello.Tello):
        #check if the current command has timed out
        current_time = time.time()
        if current_time - self.current_command_start_time > self.patrol_commands[self.current_command_index].duration:
            self.current_command_start_time = current_time
            self.current_command_index += 1
            if self.current_command_index >= len(self.patrol_commands):
                self.current_command_index = 0

        #execute the current command
        command = self.patrol_commands[self.current_command_index]
        
        if command.action == "fb":
            drone.send_rc_control(0, command.params['speed'], 0, 0)
        elif command.action == "lr":
            drone.send_rc_control(command.params['speed'], 0, 0, 0)
        elif command.action == "ud":
            drone.send_rc_control(0, 0, command.params['speed'], 0)
        elif command.action == "yv":
            drone.send_rc_control(0, 0, 0, command.params['speed'])



# Create global instance
drone_controller = DroneController()
initialise_drone = drone_controller.initialise_drone
update_controls = drone_controller.update_controls 