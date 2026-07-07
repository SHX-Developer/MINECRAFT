/**
 * Telegram Web App integration helper.
 *
 * If the page is loaded inside a Telegram Mini App, expand the viewport,
 * apply the safe-area insets (status bar, bottom bar) as CSS variables,
 * disable vertical swipes that would close the app, and expose helpers
 * for theme + platform detection.
 */

const STATE = {
  isTelegram: false,
  isMobilePlatform: false,
  platform: "unknown",
  webApp: null,
};

function readPlatform(tg) {
  const p = (tg.platform || "").toLowerCase();
  return p || "unknown";
}

function platformIsMobile(platform) {
  return (
    platform === "ios" ||
    platform === "android" ||
    platform === "android_x"
  );
}

/**
 * Initialise Telegram integration. Safe to call even if Telegram is not
 * loaded — the function no-ops in that case.
 */
export function initTelegram() {
  if (typeof window === "undefined") {
    return STATE;
  }
  const tg = window.Telegram && window.Telegram.WebApp;
  if (!tg) {
    return STATE;
  }
  STATE.isTelegram = true;
  STATE.webApp = tg;
  STATE.platform = readPlatform(tg);
  STATE.isMobilePlatform = platformIsMobile(STATE.platform);

  try {
    tg.ready();
  } catch (e) {}

  try {
    tg.expand();
  } catch (e) {}

  // Disable Telegram's vertical swipe-to-close gesture; otherwise dragging
  // to look around would close the Mini App.
  try {
    if (typeof tg.disableVerticalSwipes === "function") {
      tg.disableVerticalSwipes();
    }
  } catch (e) {}

  try {
    if (typeof tg.enableClosingConfirmation === "function") {
      tg.enableClosingConfirmation();
    }
  } catch (e) {}

  // Surface the platform for CSS targeting.
  document.body.classList.add("telegram-webapp");
  document.body.classList.add(`telegram-${STATE.platform}`);
  if (STATE.isMobilePlatform) {
    document.body.classList.add("telegram-mobile");
  }

  // Mirror the Telegram theme colours into our HUD vars (best-effort).
  try {
    const params = tg.themeParams || {};
    if (params.bg_color) {
      document.documentElement.style.setProperty("--telegram-bg", params.bg_color);
    }
  } catch (e) {}

  // Update CSS safe-area variables so the HUD doesn't get clipped by the
  // notch or the Telegram header / bottom bar.
  const updateInsets = () => {
    try {
      const top = tg.safeAreaInset && typeof tg.safeAreaInset.top === "number"
        ? tg.safeAreaInset.top
        : 0;
      const bottom = tg.safeAreaInset && typeof tg.safeAreaInset.bottom === "number"
        ? tg.safeAreaInset.bottom
        : 0;
      document.documentElement.style.setProperty("--tg-safe-top", `${top}px`);
      document.documentElement.style.setProperty("--tg-safe-bottom", `${bottom}px`);
    } catch (e) {}
  };
  updateInsets();
  // Forward Telegram viewport changes to a regular `resize` event so the
  // renderer picks up the new dimensions on rotation / Telegram chrome resize.
  const triggerResize = () => {
    updateInsets();
    try {
      window.dispatchEvent(new Event("resize"));
    } catch (e) {}
  };
  try {
    tg.onEvent && tg.onEvent("viewportChanged", triggerResize);
    tg.onEvent && tg.onEvent("safeAreaChanged", triggerResize);
  } catch (e) {}

  return STATE;
}

export function getTelegramState() {
  return STATE;
}

/**
 * Heuristic for whether we should turn on touch UI even outside Telegram —
 * any coarse-pointer device (a phone, tablet) gets the on-screen controls.
 */
export function shouldUseMobileControls() {
  if (STATE.isMobilePlatform) {
    return true;
  }
  if (typeof window === "undefined") {
    return false;
  }
  const coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  const fine = window.matchMedia && window.matchMedia("(any-pointer: fine)").matches;
  const touch = navigator.maxTouchPoints && navigator.maxTouchPoints > 0;
  const mobileUserAgent = /android|iphone|ipad|ipod|mobile/i.test(navigator.userAgent || "");
  // Don't trigger on hybrid laptops that have both a mouse and a touchscreen —
  // require BOTH coarse pointer AND touch (real phones / tablets).
  return Boolean(touch && coarse && (!fine || mobileUserAgent));
}
