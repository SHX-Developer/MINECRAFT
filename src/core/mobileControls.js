/**
 * On-screen touch controls for mobile / Telegram Web App.
 *
 * Left half of the screen: virtual joystick — drag from anywhere on the left
 *   half and the stick snaps to the touch point. Magnitude is normalised
 *   to [-1, 1] in both axes (used as analog forward / strafe).
 *
 * Right half of the screen: free look — drag to rotate the camera. A tap
 *   (touch+release without movement) on a block target triggers a break
 *   gesture; a long press triggers continuous breaking; a two-finger tap
 *   on the right side triggers a place action.
 *
 * Additionally a small column of buttons hugs the right edge: jump, crouch,
 * sprint, fly, inventory, place (right-click), and an explicit break button
 * for convenience.
 */
export class MobileControls {
  constructor({ container, input, onToggleInventory }) {
    this.container = container;
    this.input = input;
    this.onToggleInventory = onToggleInventory || (() => {});

    this.root = null;
    this.joystickArea = null;
    this.joystickKnob = null;
    this.lookArea = null;

    this.joystickActive = false;
    this.joystickPointerId = null;
    this.joystickOrigin = { x: 0, y: 0 };
    this.joystickRadius = 60;

    this.lookPointerId = null;
    this.lookLastX = 0;
    this.lookLastY = 0;
    this.lookMoved = false;
    this.lookStartTime = 0;
    this.lookStartX = 0;
    this.lookStartY = 0;
    // Touch look sensitivity multiplier applied to dx/dy before passing to
    // input.addLookDelta. The input system multiplies by MOUSE_SENSITIVITY.
    this.lookSensitivity = 1.6;

    this.breakButtonHeld = false;
    this.sprintToggled = false;
    this.orientationRequested = false;

    this._touchHandlers = [];

    this.build();
    this.bind();
  }

  build() {
    const root = document.createElement("div");
    root.id = "mobile-controls";
    root.setAttribute("aria-hidden", "true");
    root.innerHTML = `
      <div id="mc-look-area" class="mc-region"></div>
      <div id="mc-move-area" class="mc-region">
        <div id="mc-joystick-base">
          <div id="mc-joystick-knob"></div>
        </div>
      </div>
      <div id="mc-buttons-left">
        <button class="mc-btn" data-action="inventory" type="button" aria-label="Inventory">⌘</button>
        <button class="mc-btn" data-action="crouch" type="button" aria-label="Crouch">⬇</button>
        <button class="mc-btn" data-action="sprint" type="button" aria-label="Sprint">»</button>
      </div>
      <div id="mc-buttons-right">
        <button class="mc-btn mc-btn-action mc-btn-break" data-action="break" type="button" aria-label="Break">⛏</button>
        <button class="mc-btn mc-btn-action mc-btn-place" data-action="place" type="button" aria-label="Place">▣</button>
        <button class="mc-btn mc-btn-jump" data-action="jump" type="button" aria-label="Jump">▲</button>
      </div>
    `;
    this.container.appendChild(root);
    this.root = root;

    this.moveArea = root.querySelector("#mc-move-area");
    this.lookArea = root.querySelector("#mc-look-area");
    this.joystickBase = root.querySelector("#mc-joystick-base");
    this.joystickKnob = root.querySelector("#mc-joystick-knob");

    this.buttons = {
      inventory: root.querySelector('[data-action="inventory"]'),
      crouch: root.querySelector('[data-action="crouch"]'),
      sprint: root.querySelector('[data-action="sprint"]'),
      break: root.querySelector('[data-action="break"]'),
      place: root.querySelector('[data-action="place"]'),
      jump: root.querySelector('[data-action="jump"]'),
    };

    document.body.classList.add("mobile-controls-enabled");
  }

  getControlPoint(event) {
    return {
      x: event.clientX,
      y: event.clientY,
    };
  }

  bind() {
    // Joystick (left half)
    this._add(this.moveArea, "pointerdown", (e) => this.onJoystickDown(e));
    this._add(window, "pointermove", (e) => this.onPointerMove(e));
    this._add(window, "pointerup", (e) => this.onPointerUp(e));
    this._add(window, "pointercancel", (e) => this.onPointerUp(e));

    // Look (right half)
    this._add(this.lookArea, "pointerdown", (e) => this.onLookDown(e));

    // Buttons
    this._add(this.buttons.jump, "pointerdown", (e) => this.onButtonDown(e, "Space"));
    this._add(this.buttons.jump, "pointerup", (e) => this.onButtonUp(e, "Space"));
    this._add(this.buttons.jump, "pointercancel", (e) => this.onButtonUp(e, "Space"));
    this._add(this.buttons.jump, "pointerleave", (e) => this.onButtonUp(e, "Space"));

    this._add(this.buttons.crouch, "pointerdown", (e) => this.onButtonDown(e, "ShiftLeft"));
    this._add(this.buttons.crouch, "pointerup", (e) => this.onButtonUp(e, "ShiftLeft"));
    this._add(this.buttons.crouch, "pointercancel", (e) => this.onButtonUp(e, "ShiftLeft"));
    this._add(this.buttons.crouch, "pointerleave", (e) => this.onButtonUp(e, "ShiftLeft"));

    // Sprint = toggle
    this._add(this.buttons.sprint, "pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.sprintToggled = !this.sprintToggled;
      this.buttons.sprint.classList.toggle("active", this.sprintToggled);
      this.input.setVirtualKey("Sprint", this.sprintToggled);
    });

    // Inventory
    this._add(this.buttons.inventory, "pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.onToggleInventory();
    });

    // Break button — press and hold for continuous mining
    this._add(this.buttons.break, "pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.breakButtonHeld = true;
      this.input.pressMouseButton(0);
      this.buttons.break.classList.add("active");
    });
    const endBreak = (e) => {
      if (this.breakButtonHeld) {
        this.breakButtonHeld = false;
        this.input.releaseMouseButton(0);
        this.buttons.break.classList.remove("active");
      }
    };
    this._add(this.buttons.break, "pointerup", endBreak);
    this._add(this.buttons.break, "pointercancel", endBreak);
    this._add(this.buttons.break, "pointerleave", endBreak);

    // Place button — single fire
    this._add(this.buttons.place, "pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      this.input.pressMouseButton(2);
      this.input.releaseMouseButton(2);
      this.buttons.place.classList.add("active");
      setTimeout(() => this.buttons.place.classList.remove("active"), 90);
    });

    // Prevent native context menu on long-press
    const prevent = (e) => e.preventDefault();
    this._add(this.root, "contextmenu", prevent);
    this._add(this.root, "touchstart", (e) => e.preventDefault(), { passive: false });
    this._add(this.root, "touchmove", (e) => e.preventDefault(), { passive: false });
  }

  requestLandscape() {
    if (this.orientationRequested) {
      return;
    }
    this.orientationRequested = true;
    try {
      const orientation = screen.orientation;
      if (orientation && typeof orientation.lock === "function") {
        orientation.lock("landscape-primary").catch(() => {});
      }
    } catch (e) {}
  }

  _add(el, type, handler, options) {
    el.addEventListener(type, handler, options);
    this._touchHandlers.push({ el, type, handler, options });
  }

  onJoystickDown(event) {
    if (this.joystickActive) {
      return;
    }
    event.preventDefault();
    this.requestLandscape();
    const point = this.getControlPoint(event);
    this.joystickActive = true;
    this.joystickPointerId = event.pointerId;
    // Centre stick on the touch point instead of the screen corner.
    this.joystickOrigin.x = point.x;
    this.joystickOrigin.y = point.y;
    this.joystickBase.style.left = `${point.x}px`;
    this.joystickBase.style.top = `${point.y}px`;
    this.joystickBase.classList.add("active");
    this.updateJoystick(point.x, point.y);
    try {
      this.moveArea.setPointerCapture(event.pointerId);
    } catch (e) {}
  }

  onLookDown(event) {
    if (this.lookPointerId !== null) {
      return;
    }
    // Allow native handling on buttons (jump/place) sitting on top of the look area.
    if (event.target && event.target.closest && event.target.closest(".mc-btn")) {
      return;
    }
    event.preventDefault();
    this.requestLandscape();
    const point = this.getControlPoint(event);
    this.lookPointerId = event.pointerId;
    this.lookLastX = point.x;
    this.lookLastY = point.y;
    this.lookStartX = point.x;
    this.lookStartY = point.y;
    this.lookMoved = false;
    this.lookStartTime = performance.now();
    try {
      this.lookArea.setPointerCapture(event.pointerId);
    } catch (e) {}
  }

  onPointerMove(event) {
    if (event.pointerId === this.joystickPointerId) {
      const point = this.getControlPoint(event);
      this.updateJoystick(point.x, point.y);
      return;
    }
    if (event.pointerId === this.lookPointerId) {
      const point = this.getControlPoint(event);
      const dx = point.x - this.lookLastX;
      const dy = point.y - this.lookLastY;
      this.lookLastX = point.x;
      this.lookLastY = point.y;
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
        this.lookMoved = true;
      }
      this.input.addLookDelta(dx * this.lookSensitivity, dy * this.lookSensitivity);
    }
  }

  onPointerUp(event) {
    if (event.pointerId === this.joystickPointerId) {
      this.joystickActive = false;
      this.joystickPointerId = null;
      this.input.setJoystick(0, 0);
      this.joystickBase.classList.remove("active");
      // Reset knob to centre.
      this.joystickKnob.style.transform = "translate(-50%, -50%)";
      // Reset base position to default corner.
      this.joystickBase.style.left = "";
      this.joystickBase.style.top = "";
      return;
    }
    if (event.pointerId === this.lookPointerId) {
      const heldMs = performance.now() - this.lookStartTime;
      this.lookPointerId = null;
      // A short tap that didn't move triggers a break action.
      if (!this.lookMoved && heldMs < 280) {
        this.input.pressMouseButton(0);
        // release after one frame so the action system sees a click pulse.
        setTimeout(() => this.input.releaseMouseButton(0), 16);
      }
    }
  }

  updateJoystick(clientX, clientY) {
    const dx = clientX - this.joystickOrigin.x;
    const dy = clientY - this.joystickOrigin.y;
    const len = Math.hypot(dx, dy);
    const max = this.joystickRadius;
    let nx = dx;
    let ny = dy;
    if (len > max) {
      nx = (dx / len) * max;
      ny = (dy / len) * max;
    }
    this.joystickKnob.style.transform = `translate(calc(-50% + ${nx}px), calc(-50% + ${ny}px))`;
    // Map to game axes: x = strafe right (+), z = forward (+). Screen down = +y → backward.
    const stickX = nx / max;
    const stickZ = -ny / max;
    this.input.setJoystick(stickX, stickZ);
  }

  onButtonDown(event, code) {
    event.preventDefault();
    event.stopPropagation();
    this.requestLandscape();
    this.input.setVirtualKey(code, true);
    event.currentTarget.classList.add("active");
  }

  onButtonUp(event, code) {
    if (event && event.preventDefault) event.preventDefault();
    this.input.setVirtualKey(code, false);
    event.currentTarget.classList.remove("active");
  }

  setInventoryOpen(isOpen) {
    if (!this.root) return;
    this.root.classList.toggle("inventory-mode", isOpen);
  }

  destroy() {
    for (const h of this._touchHandlers) {
      try {
        h.el.removeEventListener(h.type, h.handler, h.options);
      } catch (e) {}
    }
    this._touchHandlers.length = 0;
    if (this.root && this.root.parentNode) {
      this.root.parentNode.removeChild(this.root);
    }
    document.body.classList.remove("mobile-controls-enabled");
  }
}
