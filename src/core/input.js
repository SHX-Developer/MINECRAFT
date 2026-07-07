const CONTROL_CODES = new Set([
  "KeyW",
  "KeyA",
  "KeyS",
  "KeyD",
  "KeyE",
  "KeyQ",
  "Space",
  "ShiftLeft",
  "ShiftRight",
  "Digit1",
  "Digit2",
  "Digit3",
  "Digit4",
  "Digit5",
  "Digit6",
  "Digit7",
  "Digit8",
  "Digit9",
  "Numpad1",
  "Numpad2",
  "Numpad3",
  "Numpad4",
  "Numpad5",
  "Numpad6",
  "Numpad7",
  "Numpad8",
  "Numpad9",
]);

/**
 * Detect a touch device. Telegram Web App on iOS/Android both expose touch.
 */
function detectTouchDevice() {
  if (typeof window === "undefined") {
    return false;
  }
  if (window.Telegram && window.Telegram.WebApp) {
    const platform = (window.Telegram.WebApp.platform || "").toLowerCase();
    if (platform === "ios" || platform === "android" || platform === "android_x") {
      return true;
    }
  }
  const coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  const fine = window.matchMedia && window.matchMedia("(any-pointer: fine)").matches;
  const touch = navigator.maxTouchPoints && navigator.maxTouchPoints > 0;
  const mobileUserAgent = /android|iphone|ipad|ipod|mobile/i.test(navigator.userAgent || "");
  return Boolean(touch && coarse && (!fine || mobileUserAgent));
}

export class InputManager {
  constructor(targetElement) {
    this.targetElement = targetElement;
    this.keysDown = new Set();
    this.keysPressed = new Set();
    this.mousePressed = new Set();
    this.mouseDown = new Set();
    this.mouseDeltaX = 0;
    this.mouseDeltaY = 0;
    this.wheelSteps = 0;
    this.locked = false;
    this.mouseBuffer = { x: 0, y: 0 };

    // Virtual key state — touch UI feeds in here.
    this.virtualKeysDown = new Set();
    this.virtualKeyPressEvents = [];

    // Joystick state — set by mobile UI.
    this.joystickX = 0;
    this.joystickZ = 0;

    this.isTouch = detectTouchDevice();
    // On touch devices we never use pointer lock — touch UI provides look + buttons.
    this.useTouchControls = this.isTouch;
    if (this.useTouchControls) {
      this.locked = true;
    }

    this.onClick = () => {
      if (this.useTouchControls) {
        return;
      }
      if (!this.locked) {
        this.requestPointerLock();
      }
    };

    this.onPointerLockChange = () => {
      if (this.useTouchControls) {
        return;
      }
      this.locked = document.pointerLockElement === this.targetElement;
      document.body.classList.toggle("locked", this.locked);
      if (!this.locked) {
        this.mousePressed.clear();
        this.mouseDown.clear();
      }
    };

    this.onKeyDown = (event) => {
      this.keysDown.add(event.code);
      if (!event.repeat) {
        this.keysPressed.add(event.code);
      }
      if (CONTROL_CODES.has(event.code)) {
        event.preventDefault();
      }
    };

    this.onKeyUp = (event) => {
      this.keysDown.delete(event.code);
      if (CONTROL_CODES.has(event.code)) {
        event.preventDefault();
      }
    };

    this.onMouseMove = (event) => {
      if (!this.locked || this.useTouchControls) {
        return;
      }
      this.mouseDeltaX += event.movementX;
      this.mouseDeltaY += event.movementY;
    };

    this.onMouseDown = (event) => {
      if (this.useTouchControls) {
        return;
      }
      if (!this.locked) {
        return;
      }
      this.mouseDown.add(event.button);
      this.mousePressed.add(event.button);
      event.preventDefault();
    };

    this.onMouseUp = (event) => {
      if (this.useTouchControls) {
        return;
      }
      this.mouseDown.delete(event.button);
    };

    this.onContextMenu = (event) => {
      if (this.locked || this.useTouchControls) {
        event.preventDefault();
      }
    };

    this.onWheel = (event) => {
      if (!this.locked || this.useTouchControls) {
        return;
      }
      const direction = Math.sign(event.deltaY);
      if (direction !== 0) {
        this.wheelSteps += direction;
      }
      event.preventDefault();
    };

    this.onWindowBlur = () => {
      this.keysDown.clear();
      this.keysPressed.clear();
      this.mousePressed.clear();
      this.mouseDown.clear();
      this.virtualKeysDown.clear();
      this.virtualKeyPressEvents.length = 0;
      this.joystickX = 0;
      this.joystickZ = 0;
    };

    this.targetElement.addEventListener("click", this.onClick);
    document.addEventListener("pointerlockchange", this.onPointerLockChange);
    window.addEventListener("keydown", this.onKeyDown);
    window.addEventListener("keyup", this.onKeyUp);
    window.addEventListener("mousemove", this.onMouseMove);
    window.addEventListener("mousedown", this.onMouseDown);
    window.addEventListener("mouseup", this.onMouseUp);
    window.addEventListener("contextmenu", this.onContextMenu);
    window.addEventListener("wheel", this.onWheel, { passive: false });
    window.addEventListener("blur", this.onWindowBlur);
  }

  requestPointerLock() {
    if (this.useTouchControls) {
      return;
    }
    if (!this.locked && this.targetElement.requestPointerLock) {
      try {
        this.targetElement.requestPointerLock();
      } catch (e) {
        // ignore — some browsers throw if not focused yet
      }
    }
  }

  // ---- Touch / mobile API -------------------------------------------------

  /**
   * Provide a unit-length-ish movement vector from the on-screen joystick.
   * x is strafe (right is +1), z is forward (forward is +1).
   */
  setJoystick(x, z) {
    this.joystickX = x;
    this.joystickZ = z;
  }

  /**
   * Inject a look delta from a touch drag. dx and dy are in pixels.
   * The PlayerController applies MOUSE_SENSITIVITY to these, just like a real mouse.
   */
  addLookDelta(dx, dy) {
    this.mouseDeltaX += dx;
    this.mouseDeltaY += dy;
  }

  /**
   * Press / release a virtual key. Used by on-screen buttons for jump,
   * crouch, sprint, etc.
   */
  setVirtualKey(code, down) {
    if (down) {
      if (!this.virtualKeysDown.has(code)) {
        this.virtualKeysDown.add(code);
        this.virtualKeyPressEvents.push(code);
        // Guard against unbounded growth if a virtual key is toggled many
        // times without anything consuming its press events.
        if (this.virtualKeyPressEvents.length > 32) {
          this.virtualKeyPressEvents.splice(0, this.virtualKeyPressEvents.length - 32);
        }
      }
    } else {
      this.virtualKeysDown.delete(code);
    }
  }

  /**
   * Fire-and-forget virtual key tap (press+release this frame).
   */
  pressVirtualKey(code) {
    this.virtualKeyPressEvents.push(code);
  }

  /**
   * Virtual mouse button trigger from a touch tap. button 0 = break, 2 = place.
   */
  pressMouseButton(button) {
    this.mouseDown.add(button);
    this.mousePressed.add(button);
  }

  releaseMouseButton(button) {
    this.mouseDown.delete(button);
  }

  // ---- Frame API ---------------------------------------------------------

  isKeyDown(code) {
    if (this.virtualKeysDown.has(code)) {
      return true;
    }
    return this.keysDown.has(code);
  }

  consumeKeyPress(code) {
    if (this.keysPressed.has(code)) {
      this.keysPressed.delete(code);
      return true;
    }
    const idx = this.virtualKeyPressEvents.indexOf(code);
    if (idx >= 0) {
      this.virtualKeyPressEvents.splice(idx, 1);
      return true;
    }
    return false;
  }

  consumeMouseButton(button) {
    if (!this.mousePressed.has(button)) {
      return false;
    }
    this.mousePressed.delete(button);
    return true;
  }

  isMouseDown(button) {
    return this.mouseDown.has(button);
  }

  consumeMouseDelta() {
    this.mouseBuffer.x = this.mouseDeltaX;
    this.mouseBuffer.y = this.mouseDeltaY;
    this.mouseDeltaX = 0;
    this.mouseDeltaY = 0;
    return this.mouseBuffer;
  }

  consumeWheelSteps() {
    const steps = this.wheelSteps;
    this.wheelSteps = 0;
    return steps;
  }

  getJoystick() {
    return { x: this.joystickX, z: this.joystickZ };
  }

  isUsingTouchControls() {
    return this.useTouchControls;
  }

  destroy() {
    this.targetElement.removeEventListener("click", this.onClick);
    document.removeEventListener("pointerlockchange", this.onPointerLockChange);
    window.removeEventListener("keydown", this.onKeyDown);
    window.removeEventListener("keyup", this.onKeyUp);
    window.removeEventListener("mousemove", this.onMouseMove);
    window.removeEventListener("mousedown", this.onMouseDown);
    window.removeEventListener("mouseup", this.onMouseUp);
    window.removeEventListener("contextmenu", this.onContextMenu);
    window.removeEventListener("wheel", this.onWheel);
    window.removeEventListener("blur", this.onWindowBlur);
  }
}
