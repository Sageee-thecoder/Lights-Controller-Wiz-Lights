import cv2
import time
import asyncio
import numpy as np
import math
import colorsys
import pyautogui
import HandTrackingModule as htm
from pywizlight import wizlight, PilotBuilder

########################################
wCam, hCam = 640, 480

# Your 4 WiZ bulb local IP addresses
LIGHT_IPS = [
    "192.168.5.5",
    "192.168.5.2",
    "192.168.5.8",
    "192.168.5.12"
]

# Slider Visual Constraints
sliderX1, sliderX2 = 80, 560
sliderY = 240
########################################

cap = cv2.VideoCapture(0)  # iVCam index 2
cap.set(3, wCam)
cap.set(4, hCam)
pTime = 0

bulbs = []
detector = htm.handDetector(max_hands=2)
light_state = "UNKNOWN"
last_toggle_time = 0
cooldown_delay = 1.0
prev_hue = None
prev_bright = None
prev_vol_length = None


async def control_all_bulbs(action, r=None, g=None, b=None, warm_white=None, brightness=None):
    tasks = []
    for bulb in bulbs:
        if action == "ON":
            tasks.append(bulb.turn_on())
        elif action == "OFF":
            tasks.append(bulb.turn_off())
        elif action == "COLOR":
            tasks.append(bulb.turn_on(PilotBuilder(rgb=(r, g, b))))
        elif action == "BRIGHTNESS":
            tasks.append(bulb.turn_on(PilotBuilder(brightness=brightness)))

    await asyncio.gather(*tasks)


async def main_loop():
    global pTime, light_state, last_toggle_time, bulbs, prev_hue, prev_bright, prev_vol_length

    bulbs = [wizlight(ip) for ip in LIGHT_IPS]
    print("Master Smart Room Dashboard Initialized!")

    while True:
        success, img = cap.read()
        if not success:
            break

        img = cv2.flip(img, 1)
        img = detector.findHands(img, draw=True)
        hands_dict = detector.findPosition(img, draw=False)
        current_time = time.time()

        totalFingers = -1
        r_val, g_val, b_val = 0, 255, 0
        pointer_x = int((sliderX1 + sliderX2) / 2)

        # UI Default Bars
        volPer = 0
        volBar = 400

        # === INTERFACE MODE A: TWO HANDS ACTIVE (PC VOLUME CONTROLLER) ===
        if "Hand_1" in hands_dict and "Hand_2" in hands_dict:
            lmList1 = hands_dict["Hand_1"]
            lmList2 = hands_dict["Hand_2"]

            # Extract Index Finger Tips (ID 8) across both hands
            x1, y1 = int(lmList1[8][1]), int(lmList1[8][2])
            x2, y2 = int(lmList2[8][1]), int(lmList2[8][2])
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

            cv2.circle(img, (x1, y1), 10, (255, 0, 128), cv2.FILLED)
            cv2.circle(img, (x2, y2), 10, (255, 0, 128), cv2.FILLED)
            cv2.line(img, (x1, y1), (x2, y2), (255, 0, 128), 2)
            cv2.circle(img, (cx, cy), 6, (0, 0, 255), cv2.FILLED)

            # Measure distance and map safely with fixed ranges
            length = math.hypot(x2 - x1, y2 - y1)
            volBar = np.interp(length, (50, 300), (400, 150))
            volPer = np.interp(length, (50, 300), (0, 100))

            if prev_vol_length is not None:
                if length > prev_vol_length + 5:
                    pyautogui.press('volumeup')
                elif length < prev_vol_length - 5:
                    pyautogui.press('volumedown')

            prev_vol_length = length

            cv2.putText(img, f'MODE: PC VOLUME ({int(volPer)}%)', (180, 70),
                        cv2.FONT_HERSHEY_COMPLEX, 0.7, (255, 0, 128), 2)

            cv2.rectangle(img, (50, 150), (85, 400), (200, 200, 200), 2)
            cv2.rectangle(img, (50, int(volBar)), (85, 400), (255, 0, 128), cv2.FILLED)

        # === INTERFACE MODE B: SINGLE HAND ACTIVE (LIGHT SYSTEMS) ===
        elif "Hand_1" in hands_dict:
            cv2.line(img, (sliderX1, sliderY), (sliderX2, sliderY), (100, 100, 100), 10, cv2.LINE_AA)

            lmList1 = hands_dict["Hand_1"]
            detector.lmList = lmList1
            fingers = detector.fingersUp()
            totalFingers = fingers.count(1)

            # 🖐️ 5 FINGERS -> COLOR SLIDER
            if totalFingers == 5:
                # FIXED: Added [1] to grab raw integer X value
                index_x = int(lmList1[8][1])
                pointer_x = max(sliderX1, min(index_x, sliderX2))

                hue = float(np.interp(pointer_x, (sliderX1, sliderX2), (0.0, 1.0)))
                r_float, g_float, b_float = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                r_val = int(r_float * 255)
                g_val = int(g_float * 255)
                b_val = int(b_float * 255)

                if prev_hue is None or abs(hue - prev_hue) > 0.04:
                    try:
                        await control_all_bulbs("COLOR", r=r_val, g=g_val, b=b_val)
                        light_state = "RAINBOW"
                        prev_hue = hue
                    except Exception as e:
                        print(e)

                cv2.line(img, (sliderX1, sliderY), (pointer_x, sliderY), (b_val, g_val, r_val), 10, cv2.LINE_AA)
                cv2.circle(img, (pointer_x, sliderY), 16, (b_val, g_val, r_val), cv2.FILLED)
                cv2.circle(img, (pointer_x, sliderY), 18, (255, 255, 255), 2, cv2.LINE_AA)

                cv2.putText(img, 'MODE: HUE COLOR SLIDER', (180, 70),
                            cv2.FONT_HERSHEY_COMPLEX, 0.7, (b_val, g_val, r_val), 2)

            # ✌️ 2 FINGERS -> DIMMER
            elif totalFingers == 2:
                # FIXED: Target correct element indexes for Wrist (ID 0)
                wrist_x = int(lmList1[0][1])
                wrist_y = int(lmList1[0][2])

                cv2.line(img, (0, wrist_y), (wCam, wrist_y), (0, 255, 0), 1)
                cv2.line(img, (wrist_x, 0), (wrist_x, hCam), (0, 255, 0), 1)
                cv2.circle(img, (wrist_x, wrist_y), 12, (0, 255, 0), 2)

                bright_percentage = np.interp(wrist_y, (100, 400), (100, 0))
                wiz_bright = int(np.interp(wrist_y, (100, 400), (255, 10)))

                if prev_bright is None or abs(wiz_bright - prev_bright) > 20:
                    try:
                        await control_all_bulbs("BRIGHTNESS", brightness=wiz_bright)
                        light_state = f"DIM ({int(bright_percentage)}%)"
                        prev_bright = wiz_bright
                    except Exception as e:
                        print(e)

                cv2.putText(img, f'MODE: MATRIX DIMMER ({light_state})', (160, 70),
                            cv2.FONT_HERSHEY_COMPLEX, 0.7, (0, 255, 0), 2)

            # OTHER PRESETS
            else:
                if current_time - last_toggle_time > cooldown_delay:
                    if totalFingers == 0 and light_state != "OFF":
                        try:
                            await control_all_bulbs("OFF"); light_state = "OFF"; last_toggle_time = current_time
                        except Exception as e:
                            print(e)
                    elif totalFingers == 1 and light_state != "BLUE":
                        try:
                            await control_all_bulbs("COLOR", r=0, g=0,
                                                    b=255); light_state = "BLUE"; last_toggle_time = current_time
                        except Exception as e:
                            print(e)
                    elif totalFingers == 3 and light_state != "PINK":
                        try:
                            await control_all_bulbs("COLOR", r=255, g=20,
                                                    b=147); light_state = "PINK"; last_toggle_time = current_time
                        except Exception as e:
                            print(e)
                    elif totalFingers == 4 and light_state != "PURPLE":
                        try:
                            await control_all_bulbs("COLOR", r=128, g=0,
                                                    b=128); light_state = "PURPLE"; last_toggle_time = current_time
                        except Exception as e:
                            print(e)

                cv2.putText(img, f'Fingers: {totalFingers} ({light_state})', (210, 70),
                            cv2.FONT_HERSHEY_COMPLEX, 0.7, (0, 255, 0), 2)

        hTime = time.time()
        fps = 1 / (hTime - pTime)
        pTime = hTime
        cv2.putText(img, f'FPS: {int(fps)}', (40, 50), cv2.FONT_HERSHEY_COMPLEX, 0.6, (255, 50, 50), 1)

        cv2.imshow("Smart Room Dashboard Master", img)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(main_loop())
