import pygame
import tello_video

PYGAME_WINDOW_DIMENSIONS = (800,600)
pygame_window = None

def initialise_pygame():
    pygame.init()
    global pygame_window
    pygame_window = pygame.display.set_mode(PYGAME_WINDOW_DIMENSIONS)


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
                tello_video.take_a_snapshot()

    return running


def quit_pygame():
    pygame.quit()


def get_dimensions():
    """Return the current pygame window dimensions as (width, height)"""
    return PYGAME_WINDOW_DIMENSIONS  # These should be your pygame window dimensions


def blit_frame(frame):
    global pygame_window
    pygame.surfarray.blit_array(pygame_window, frame)