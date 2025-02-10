from djitellopy import tello
import pygame
import logging
from dataclasses import dataclass
from typing import Tuple, Dict
import time

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
                drone.takeoff()
                self.is_currently_flying = True
                had_input = True
                self.last_takeoff_time = current_time

            # Emergency stop
            if self.get_key("SPACE"):
                self.speeds = dict.fromkeys(self.speeds, 0)
                had_input = True

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


# Create global instance
drone_controller = DroneController()
initialise_drone = drone_controller.initialise_drone
update_controls = drone_controller.update_controls 