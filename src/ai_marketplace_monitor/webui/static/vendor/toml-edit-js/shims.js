import originalInit, { initSync as originalInitSync } from "./index.js"
import { edit as original_edit, parse as original_parse, stringify as original_stringify } from "./index.js"

const wasmUrl = new URL("index_bg.wasm", import.meta.url);
let wasmBuffer, wasm, nodeFs;
const isDeno = typeof globalThis.Deno !== "undefined";
const isNode = globalThis.process?.release?.name === "node";
const isBun = typeof globalThis.Bun !== "undefined";
const isBrowser = typeof globalThis.window !== "undefined";
const isFileProtocol = wasmUrl.protocol === "file:";
if ((isNode || isBun) && isFileProtocol) {
    nodeFs = await import("node:fs");
}

function __initWasmCodeSync() {
    if (isNode || isBun) {
        if (!isFileProtocol) {
            throw new Error("synchronous init only supports file protocol in node/bun");
        }
        wasmBuffer = nodeFs.readFileSync(wasmUrl);
    } else if (isDeno) {
        wasmBuffer = Deno.readFileSync(wasmUrl);
    } else {
        throw new Error("synchronous init not support for current platform");
    }
    return wasmBuffer;
}

async function __initWasmCodeAsync() {
    if (isNode || isBun) {
        if (isFileProtocol) {
            wasmBuffer = await nodeFs.promises.readFile(wasmUrl);
        } else {
            wasmBuffer = wasmUrl;
        }
    } else if (isDeno) {
        if (isFileProtocol) {
            wasmBuffer = await Deno.readFile(wasmUrl);
        } else {
            wasmBuffer = wasmUrl;
        }
    } else if (isBrowser) {
        wasmBuffer = wasmUrl;
    } else {
        throw new Error("asynchronous init not support for current platform");
    }
    return wasmBuffer;
}

function wrapSyncInitArg(module_or_path) {
    if (module_or_path === undefined) {
        return undefined;
    }
    if (
        module_or_path !== null
        && typeof module_or_path === "object"
    ) {
        if (Object.hasOwn(module_or_path, "module")) {
            return module_or_path;
        }
        if (Object.keys(module_or_path).length === 0) {
            return undefined;
        }
    }
    return { module: module_or_path };
}

function wrapInitArg(module_or_path) {
    if (module_or_path === undefined) {
        return undefined;
    }
    if (
        module_or_path !== null
        && typeof module_or_path === "object"
    ) {
        if (Object.hasOwn(module_or_path, "module_or_path")) {
            return module_or_path;
        }
        if (
            Object.getPrototypeOf(module_or_path) === Object.prototype
            && Object.keys(module_or_path).length === 0
        ) {
            return undefined;
        }
    }
    return { module_or_path };
}

function isInitialized() {
    return wasm !== undefined;
}

export function initSync(module_or_path) {
    if (isInitialized()) return wasm;
    if (module_or_path === undefined) {
        module_or_path = __initWasmCodeSync();
    }
    const wrapped = wrapSyncInitArg(module_or_path);
    wasm = wrapped === undefined
        ? originalInitSync()
        : originalInitSync(wrapped);
    return wasm;
}

export async function init(module_or_path) {
    if (isInitialized()) return wasm;
    if (module_or_path === undefined) {
        module_or_path = await __initWasmCodeAsync();
    }
    const wrapped = wrapInitArg(module_or_path);
    wasm = wrapped === undefined
        ? await originalInit()
        : await originalInit(wrapped);
    return wasm;
}

function checkInit() {
    if (!isInitialized()) {
        throw new Error("WASM module not initialized");
    }
}

export default init;

export function edit(input, path, value, opts) { checkInit(); if (typeof input !== "string") { throw new Error("Invalid parameter: input must be a string"); }
if (typeof path !== "string") { throw new Error("Invalid parameter: path must be a string"); }
; return original_edit(input, path, value, opts); }
export function parse(input) { checkInit(); if (typeof input !== "string") { throw new Error("Invalid parameter: input must be a string"); }; return original_parse(input); }
export function stringify(input, opts) { checkInit(); ; return original_stringify(input, opts); }