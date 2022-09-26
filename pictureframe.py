import sys
import datetime
import queue
import os
import random
import pygame

from PIL import Image, ExifTags

screen_size = screen_width, screen_height = 1920, 1080
image_time = 30

images = {
    "solar": [],
    "grid": [],
    "offline": []
}


def read_images():
    for subdir in images.keys():
        im_dir = os.scandir("images/" + subdir)
        for im in im_dir:
            if im.name == "README":
                continue
            images[subdir].append(im.path)
        random.shuffle(images[subdir])


def next_image(image_idx, img_select):
    if image_idx > len(images[img_select]) - 1:
        image_idx = 0
    filepath = images[img_select][image_idx]
    image_idx += 1
    rotate = 0
    try:
        image=Image.open(filepath)
        for orientation_tag in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation_tag] == 'Orientation':
                break
        exif = image._getexif()
        if exif != None:
            if exif[orientation_tag] == 3:
                rotate = 180
            elif exif[orientation_tag] == 6:
                rotate = 270
            elif exif[orientation_tag] == 8:
                rotate = 90
    except (AttributeError, KeyError, IndexError):
        # cases: image don't have getexif
        pass

    img = pygame.image.load(filepath).convert_alpha()
    if rotate != 0:
        img = pygame.transform.rotate(img, rotate)
    img_rect = img.get_rect()
    scale = (1000, 1000)
    pos = (0, 0)
    img_width = abs(img_rect.right - img_rect.left)
    img_height = abs(img_rect.top - img_rect.bottom)
    if img_width / img_height > screen_width / screen_height:
        scale = (screen_width, screen_width / img_width * img_height)
        pos = (0, (screen_height - scale[1]) / 2)
    else:
        scale = (screen_height / img_height * img_width, screen_height)
        pos = ((screen_width - scale[0]) / 2, 0)
    img = pygame.transform.smoothscale(img, scale)
    return img, pos, image_idx


def get_bar(pos):
    bar = None
    if pos != None:
        if pos[0] > 0:
            bar = pygame.Surface((pos[0]+2, screen_height), flags=pygame.SRCALPHA)
        else:
            bar = pygame.Surface((screen_width, pos[1]+2), flags=pygame.SRCALPHA)
    return bar


def blit_bar(screen, pos, bar, a):
    if bar != None:
        bar.fill((0,0,0,a))
        screen.blit(bar, (0,0))
        if pos[0] > 0:
            screen.blit(bar, (screen_width-pos[0]-1,0))
        else:
            screen.blit(bar, (0, screen_height-pos[1]-1))


def blit_img_with_bar(screen, img, pos, alpha):
    bar = get_bar(pos)
    img.set_alpha(alpha)
    screen.blit(img, pos)
    blit_bar(screen, pos, bar, alpha)


def transition(screen, img, pos, prev_img, prev_pos, overlay):
    clock = pygame.time.Clock()
    for  a in range(0,260,5):
        if prev_img != None:
            blit_img_with_bar(screen, prev_img, prev_pos, 255)
        blit_img_with_bar(screen, img, pos, a)
        blit_overlay(screen, overlay)
        pygame.display.flip()
        clock.tick(25)


def blit_overlay(screen, overlay):
    if overlay == None:
        return
    for o in overlay:
        screen.blit(o["surface"], o["pos"])


def main(terminate_event, pvdata_queue):
    pygame.init()
    sans_font = None
    if pygame.font.get_init():
        sans_font = pygame.font.SysFont("Calibri", 70)
    else:
        print("pygame.font.init() failed. This module is optional and requires SDL_ttf as a dependency. Not text can be shown")
    screen = pygame.display.set_mode(screen_size)
    read_images()
    image_idx = 0
    img_display_time = None
    pvdata_record = None
    img_select = "offline"
    prev_img_select = img_select
    prev_img = None
    prev_pos = None
    img = None
    pos = None
    prev_timestamp = None
    overlay = None
    while 1:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE or event.key == pygame.K_x or event.key == pygame.K_q:
                    terminate_event.set()

        if terminate_event.is_set():
            break

        try:
            prev_img_select = img_select
            pvdata_record = pvdata_queue.get(False) # don't block
            img_select = pvdata_record["img_select"]
            if not pvdata_record["IsOnline"]:
                overlay = None
        except queue.Empty:
            pass

        if img_display_time == None \
                or (datetime.datetime.now() - img_display_time).seconds > image_time \
                or img_select != prev_img_select:
            img_display_time = datetime.datetime.now()
            img, pos, image_idx = next_image(image_idx, img_select)
            transition(screen, img, pos, prev_img, prev_pos, overlay)
            prev_img = img
            prev_pos = pos

        if pygame.font.get_init() and pvdata_record != None and pvdata_record["datetime"] != prev_timestamp:
            if "IsOnline" in pvdata_record and pvdata_record["IsOnline"] and "P_Grid" in pvdata_record \
                    and "P_PV" in pvdata_record and "P_Load" in pvdata_record:
                pv = 0
                if pvdata_record['P_PV'] != None:
                    pv = pvdata_record['P_PV']

                grid_surface = sans_font.render(f"Grid: {pvdata_record['P_Grid']:.1f} W", True, (255, 255, 255, 255))
                solar_surface = sans_font.render(f"Solar: {pv:.1f} W", True, (255, 255, 255, 255))
                house_surface = sans_font.render(f"House: {-pvdata_record['P_Load']:.1f} W", True, (255, 255, 255, 255))
                margin = 40
                text_height = grid_surface.get_rect().bottom
                y_text_pos = screen_height - margin - text_height
                grid_text_pos = margin
                solar_text_pos = screen_width / 2 - solar_surface.get_rect().right / 2
                house_text_pos = screen_width - house_surface.get_rect().right - margin
                overlay = [
                    {"surface": grid_surface, "pos": (grid_text_pos, y_text_pos)},
                    {"surface": solar_surface, "pos": (solar_text_pos, y_text_pos)},
                    {"surface": house_surface, "pos": (house_text_pos, y_text_pos)},
                ]
                blit_img_with_bar(screen, img, pos, 255)
                blit_overlay(screen, overlay)
                pygame.display.flip()
            
        # Delay and/or exit
        if terminate_event.wait(timeout=1.0):
            break

