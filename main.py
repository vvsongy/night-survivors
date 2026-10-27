"""Night Survivors - the window: drawing, input, sound and the game loop.

Rules live in rules.py; this file only shows them, plays their events and feeds in the
player's input. The loop is async and awaits asyncio.sleep(0) once per frame, so pygbag
can run it in a web browser.
"""

import asyncio
import math
import os
import random

import pygame

import rules

CFG = rules.load_config()
WIDTH = CFG["screen"]["width"]
HEIGHT = CFG["screen"]["height"]
TILE = CFG["screen"]["tile_size"]
FPS = 60

ASSET_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
SOUND_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), CFG["sound"]["folder"])
FEEL = CFG["feel"]

COLORS = {
    "spark": (255, 217, 74),
    "ring": (255, 236, 150),
    "hp_back": (60, 60, 72),
    "hp_bar": (224, 74, 74),
    "xp_bar": (74, 150, 224),
    "text": (232, 232, 240),
    "shade": (12, 12, 20, 190),
    "card": (34, 36, 52, 235),
    "card_border": (120, 200, 255),
    "number": (255, 244, 180),
    "flash_fill": (255, 246, 220),
    "flash_ring": (255, 255, 255),
}

# The World is kept here so a short play of the game is one object we can look at.
world = None

# Finished pictures and fonts, filled in by load_pictures() and load_fonts().
pictures = {}
big_pictures = {}
FONTS = {}

# The sounds from make_sounds.py, and whether the audio device opened.
sounds = {}
sound_is_on = False
last_sound = {}

# The short-lived things the events turn into: floating numbers, death flashes and
# the shake left after the hero is hurt. The camera shift is part of the shake.
EFFECTS = {"numbers": [], "flashes": [], "shake": 0.0, "camera": (0.0, 0.0)}


def needed_art():
    names = [CFG["screen"]["tile_art"], CFG["hero"]["art"], CFG["gem"]["art"]]
    names += list(CFG["gem"]["art_by_xp"].values())
    names += [enemy["art"] for enemy in CFG["enemies"].values()]
    names += [weapon["art"] for weapon in CFG["weapons"].values() if "art" in weapon]
    return names


def load_pictures():
    """Read the files make_assets.py built. No Pillow here: a browser cannot run it."""
    for name in needed_art():
        path = os.path.join(ASSET_FOLDER, name)
        if not os.path.exists(path):
            raise SystemExit(f"Missing picture {path} - run  python make_assets.py  first.")
        pictures[name] = pygame.image.load(path).convert_alpha()


def load_fonts():
    for size, name in ((22, "small"), (30, "mid"), (44, "big")):
        FONTS[name] = pygame.font.Font(None, size)


def sound_file(name):
    for suffix in (".ogg", ".wav"):
        path = os.path.join(SOUND_FOLDER, name + suffix)
        if os.path.exists(path):
            return path
    return None


def load_sounds():
    """Read the files make_sounds.py built. No wave module here: a browser cannot run it."""
    global sound_is_on
    missing = [name for name in CFG["sound"]["sounds"] if sound_file(name) is None]
    if missing:
        raise SystemExit(
            f"Missing sound {', '.join(missing)} - run  python make_sounds.py  first."
        )
    try:
        pygame.mixer.init()
        for name in CFG["sound"]["sounds"]:
            sounds[name] = pygame.mixer.Sound(sound_file(name))
    except pygame.error as problem:
        print(f"No sound: {problem}")
        return
    sound_is_on = True


def play(name):
    if not sound_is_on:
        return
    now = pygame.time.get_ticks() / 1000.0
    if now - last_sound.get(name, -99.0) < CFG["sound"]["repeat_seconds"]:
        return
    last_sound[name] = now
    sounds[name].play()


def blit_centred(screen, picture, x, y):
    screen.blit(picture, (x - picture.get_width() / 2, y - picture.get_height() / 2))


def blit_mid_text(screen, text, x, y, font_name="small", colour=None):
    picture = FONTS[font_name].render(text, True, colour or COLORS["text"])
    screen.blit(picture, (x - picture.get_width() / 2, y))


def to_screen_x(world, x):
    return x - world.hero_x + WIDTH / 2 + EFFECTS["camera"][0]


def to_screen_y(world, y):
    return y - world.hero_y + HEIGHT / 2 + EFFECTS["camera"][1]


def to_world(world, screen_x, screen_y):
    shift_x, shift_y = EFFECTS["camera"]
    return (screen_x + world.hero_x - WIDTH / 2 - shift_x, screen_y + world.hero_y - HEIGHT / 2 - shift_y)


def new_world():
    global world
    world = rules.World(CFG)
    EFFECTS["numbers"] = []
    EFFECTS["flashes"] = []
    EFFECTS["shake"] = 0.0
    EFFECTS["camera"] = (0.0, 0.0)
    return world


# ---------- the feel: what an event turns into on screen ----------


def apply_events(events):
    for event in events:
        kind = event[0]
        if kind == "enemy_hit":
            add_number(event[1], event[2], str(int(event[3])))
            play("hit")
        elif kind == "enemy_died":
            add_flash(event[1], event[2])
        elif kind == "gem_taken":
            play("gem")
        elif kind == "hero_hurt":
            EFFECTS["shake"] = FEEL["shake_seconds"]
            play("hurt")
        elif kind == "level_up":
            play("level")
        elif kind in ("game_over", "victory"):
            play("end")


def add_number(x, y, text):
    EFFECTS["numbers"].append({"x": x, "y": y, "text": text, "left": FEEL["number_seconds"]})
    del EFFECTS["numbers"][: -FEEL["number_limit"]]


def add_flash(x, y):
    EFFECTS["flashes"].append({"x": x, "y": y, "left": FEEL["flash_seconds"]})
    del EFFECTS["flashes"][: -FEEL["flash_limit"]]


def update_effects(seconds):
    for group in ("numbers", "flashes"):
        for item in EFFECTS[group]:
            item["left"] -= seconds
        EFFECTS[group] = [item for item in EFFECTS[group] if item["left"] > 0.0]
    EFFECTS["shake"] = max(0.0, EFFECTS["shake"] - seconds)
    strength = EFFECTS["shake"] / FEEL["shake_seconds"] * FEEL["shake_pixels"]
    EFFECTS["camera"] = (random.uniform(-strength, strength), random.uniform(-strength, strength))


def draw_effects(screen):
    for flash in EFFECTS["flashes"]:
        gone = 1.0 - flash["left"] / FEEL["flash_seconds"]
        radius = FEEL["flash_start"] + FEEL["flash_grow"] * gone
        size = int(radius * 2) + 6
        surface = pygame.Surface((size, size), pygame.SRCALPHA)
        centre = (size // 2, size // 2)
        pygame.draw.circle(surface, (*COLORS["flash_fill"], int(110 * (1.0 - gone))), centre, radius)
        pygame.draw.circle(surface, (*COLORS["flash_ring"], int(255 * (1.0 - gone))), centre, radius, 3)
        blit_centred(screen, surface, to_screen_x(world, flash["x"]), to_screen_y(world, flash["y"]))
    for number in EFFECTS["numbers"]:
        strength = number["left"] / FEEL["number_seconds"]
        colour = tuple(int(part * strength) for part in COLORS["number"])
        rise = FEEL["number_lift"] + (1.0 - strength) * FEEL["number_rise"]
        picture = FONTS["small"].render(number["text"], True, colour)
        screen.blit(
            picture,
            (to_screen_x(world, number["x"]) - picture.get_width() / 2, to_screen_y(world, number["y"]) - rise),
        )


def draw_floor(screen):
    shift_x, shift_y = EFFECTS["camera"]
    left = world.hero_x - WIDTH / 2 - shift_x
    top = world.hero_y - HEIGHT / 2 - shift_y
    first_col = math.floor(left / TILE)
    first_row = math.floor(top / TILE)
    tile = pictures[CFG["screen"]["tile_art"]]
    for row in range(int(HEIGHT / TILE) + 2):
        for col in range(int(WIDTH / TILE) + 2):
            screen.blit(tile, (first_col * TILE - left + col * TILE, first_row * TILE - top + row * TILE))


def gem_picture(xp):
    names = CFG["gem"]["art_by_xp"]
    return pictures[names.get(str(int(xp)), CFG["gem"]["art"])]


def bigger(name, scale):
    """Some enemies, like the boss, are drawn twice as big."""
    if scale == 1:
        return pictures[name]
    key = (name, scale)
    if key not in big_pictures:
        picture = pictures[name]
        big_pictures[key] = pygame.transform.scale(
            picture, (picture.get_width() * scale, picture.get_height() * scale)
        )
    return big_pictures[key]


def draw_units(screen):
    for drop in world.gems:
        x = to_screen_x(world, drop.x)
        y = to_screen_y(world, drop.y)
        picture = gem_picture(drop.xp)
        edge = max(picture.get_width(), picture.get_height()) / 2
        if -edge < x < WIDTH + edge and -edge < y < HEIGHT + edge:
            blit_centred(screen, picture, x, y)
    for enemy in world.enemies:
        x = to_screen_x(world, enemy.x)
        y = to_screen_y(world, enemy.y)
        info = CFG["enemies"][enemy.kind]
        picture = bigger(info["art"], info.get("scale", 1))
        edge = max(picture.get_width(), picture.get_height()) / 2
        if -edge < x < WIDTH + edge and -edge < y < HEIGHT + edge:
            blit_centred(screen, picture, x, y)
    for spark in world.sparks:
        pygame.draw.circle(
            screen, COLORS["spark"], (to_screen_x(world, spark.x), to_screen_y(world, spark.y)), spark.radius
        )
    blit_centred(
        screen,
        pictures[CFG["hero"]["art"]],
        WIDTH / 2 + EFFECTS["camera"][0],
        HEIGHT / 2 + EFFECTS["camera"][1],
    )
    draw_weapons_on_top(screen)


def draw_weapons_on_top(screen):
    """The weapons that are not flying: the ring circle and the turning blades."""
    centre = (WIDTH / 2 + EFFECTS["camera"][0], HEIGHT / 2 + EFFECTS["camera"][1])
    for kind in world.weapons:
        weapon = CFG["weapons"][kind]
        if weapon["behaviour"] == "aura":
            radius = world.weapon_stat(kind, "radius")
            pygame.draw.circle(screen, COLORS["ring"], centre, radius, 3)
        elif weapon["behaviour"] == "orbit":
            blade = pictures[weapon["art"]]
            for x, y in world.blade_points:
                angle = -math.degrees(math.atan2(y - world.hero_y, x - world.hero_x)) - 90
                blit_centred(screen, pygame.transform.rotate(blade, angle), to_screen_x(world, x), to_screen_y(world, y))


def time_text(seconds):
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def draw_hud(screen):
    bar_width = 150
    health = max(0.0, world.hp / world.max_hp)
    pygame.draw.rect(screen, COLORS["hp_back"], (12, 12, bar_width, 14))
    pygame.draw.rect(screen, COLORS["hp_bar"], (12, 12, bar_width * health, 14))
    screen.blit(FONTS["small"].render(f"{int(world.hp)} / {int(world.max_hp)}", True, COLORS["text"]), (12, 30))

    xp = min(1.0, world.xp / world.xp_needed())
    pygame.draw.rect(screen, COLORS["hp_back"], (12, 54, bar_width, 10))
    pygame.draw.rect(screen, COLORS["xp_bar"], (12, 54, bar_width * xp, 10))
    screen.blit(FONTS["small"].render(f"Lv {world.level}", True, COLORS["text"]), (12, 68))

    clock_text = FONTS["small"].render(
        f"{time_text(world.elapsed)} / {time_text(CFG['run']['duration'])}", True, COLORS["text"]
    )
    screen.blit(clock_text, (WIDTH - clock_text.get_width() - 12, 12))

    owned = [f"{CFG['weapons'][kind]['short']} {level}" for kind, level in world.weapons.items()]
    owned += [f"{CFG['items'][kind]['short']} {level}" for kind, level in world.items.items()]
    blit_mid_text(screen, "  ".join(owned), WIDTH / 2, HEIGHT - 28)


def card_rects():
    height, gap, margin = 110, 18, 28
    count = len(world.cards)
    top = HEIGHT / 2 - (count * height + (count - 1) * gap) / 2
    return [
        pygame.Rect(margin, top + index * (height + gap), WIDTH - 2 * margin, height)
        for index in range(count)
    ]


def draw_cards(screen):
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill(COLORS["shade"])
    screen.blit(overlay, (0, 0))
    blit_mid_text(screen, "CHOOSE A CARD", WIDTH / 2, HEIGHT / 2 - (len(world.cards) * 128) / 2 - 52, "big")
    for rect, card in zip(card_rects(), world.cards):
        pygame.draw.rect(screen, COLORS["card"], rect, border_radius=10)
        pygame.draw.rect(screen, COLORS["card_border"], rect, 3, border_radius=10)
        blit_mid_text(screen, card["label"], rect.centerx, rect.top + 12, "mid")
        if card["level"] is not None:
            blit_mid_text(screen, f"Lv {card['level']}", rect.centerx, rect.top + 48, "small")
        blit_mid_text(screen, card["text"], rect.centerx, rect.top + 78, "small")


def pick_card(screen_x, screen_y):
    for index, rect in enumerate(card_rects()):
        if rect.collidepoint(screen_x, screen_y):
            world.choose_card(index)
            return


def draw_centre(screen, big_text, small_text):
    overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    overlay.fill(COLORS["shade"])
    screen.blit(overlay, (0, 0))
    blit_mid_text(screen, big_text, WIDTH / 2, HEIGHT / 2 - 40, "big")
    for index, line in enumerate(small_text):
        blit_mid_text(screen, line, WIDTH / 2, HEIGHT / 2 + 10 + index * 22)


async def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Night Survivors")
    load_pictures()
    load_fonts()
    load_sounds()
    clock = pygame.time.Clock()

    new_world()
    accumulator = 0.0
    finger = None
    touched = False
    mouse_moved = False
    paused = False
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_p:
                    paused = not paused
            elif event.type == pygame.MOUSEMOTION:
                mouse_moved = True
            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                if event.type == pygame.FINGERDOWN:
                    finger = (event.x * WIDTH, event.y * HEIGHT)
                    touched = True
                point = finger if event.type == pygame.FINGERDOWN else event.pos
                if world.state == "level_up":
                    pick_card(*point)
                elif world.state != "running":
                    new_world()
                    paused = False
            elif event.type == pygame.FINGERMOTION:
                finger = (event.x * WIDTH, event.y * HEIGHT)
                touched = True
            elif event.type == pygame.FINGERUP:
                finger = None
                touched = True

        # A phone never moves the hero with a mouse, and before the first touch or
        # mouse move the hero just stands still.
        if finger is not None:
            point = finger
        elif touched:
            point = None
        elif mouse_moved:
            point = pygame.mouse.get_pos()
        else:
            point = None

        if world.state == "running":
            if point is None:
                world.set_move_target(None, None)
            else:
                world.set_move_target(*to_world(world, *point))

        accumulator += min(clock.tick(FPS), 250) / 1000.0
        steps = 0
        while accumulator >= rules.FIXED_STEP and steps < 8:
            if not paused:
                apply_events(world.step())
                update_effects(rules.FIXED_STEP)
            accumulator -= rules.FIXED_STEP
            steps += 1
        if steps == 8:
            accumulator = 0.0

        draw_floor(screen)
        draw_units(screen)
        draw_effects(screen)
        draw_hud(screen)
        if world.state == "level_up":
            draw_cards(screen)
        elif paused and world.state == "running":
            draw_centre(screen, "PAUSED", ["Press P to play on"])
        elif world.state in ("game_over", "victory"):
            title = "VICTORY" if world.state == "victory" else "GAME OVER"
            draw_centre(
                screen,
                title,
                [
                    f"Time {time_text(world.elapsed)}",
                    f"Kills {world.kills}",
                    f"Level {world.level}",
                    "Click or tap to play again",
                ],
            )
        pygame.display.flip()

        await asyncio.sleep(0)

    pygame.quit()


if __name__ == "__main__":
    asyncio.run(main())
