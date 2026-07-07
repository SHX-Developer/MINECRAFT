import * as THREE from "three";
import { FOG_FAR, FOG_NEAR, RENDER_PIXEL_RATIO_MAX, SKY_COLOR } from "../utils/constants.js";

export function getGameViewportSize() {
  const forceLandscapeLeft = document.body.classList.contains("force-landscape-left");
  const portraitViewport = window.innerHeight > window.innerWidth;
  if (forceLandscapeLeft && portraitViewport) {
    return {
      width: window.innerHeight,
      height: window.innerWidth,
    };
  }
  return {
    width: window.innerWidth,
    height: window.innerHeight,
  };
}

export function createRenderer(canvas) {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: false,
    powerPreference: "high-performance",
  });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, RENDER_PIXEL_RATIO_MAX));
  const { width, height } = getGameViewportSize();
  renderer.setSize(width, height, false);
  renderer.sortObjects = true;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(SKY_COLOR);
  scene.fog = new THREE.Fog(SKY_COLOR, FOG_NEAR, FOG_FAR);

  return { renderer, scene };
}

export function resizeRenderer(renderer, camera) {
  const { width, height } = getGameViewportSize();
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
}
