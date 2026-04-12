// toml-edit-js shims — wraps the WASM-backed toml_edit port.
// See LICENSE-AND-VERSION.json for provenance.

let wasm;
let original_edit;
let original_parse;
let original_stringify;
let initialized = false;

function checkInit() {
    if (!initialized) {
        throw new Error("toml-edit-js: call init() first");
    }
}

// Detect environment (browser vs Node) and load accordingly.
async function init(input) {
    if (initialized) return;

    // Browser path: fetch the .wasm sidecar.
    if (typeof window !== "undefined" || typeof globalThis.fetch === "function") {
        const { default: initWasm, edit, parse, stringify } = await import("./index.js");

        // Resolve the WASM URL relative to this module.
        let wasmUrl;
        if (input) {
            wasmUrl = input;
        } else {
            // import.meta.url gives us the URL of this script file.
            const base = new URL(".", import.meta.url);
            wasmUrl = new URL("index_bg.wasm", base);
        }

        await initWasm(wasmUrl);
        original_edit = edit;
        original_parse = parse;
        original_stringify = stringify;
        initialized = true;
        return;
    }

    // Node.js path (for testing / server-side usage).
    try {
        const fs = await import("fs");
        const path = await import("path");
        const { default: initWasm, edit, parse, stringify } = await import("./index.js");

        const wasmPath = input || path.join(
            path.dirname(new URL(import.meta.url).pathname),
            "index_bg.wasm"
        );
        const wasmBytes = fs.readFileSync(wasmPath);
        await initWasm(wasmBytes);
        original_edit = edit;
        original_parse = parse;
        original_stringify = stringify;
        initialized = true;
    } catch (err) {
        // If we're in a bundled environment where Node APIs aren't
        // available, fall through — the caller will see the
        // "call init() first" error on use.
        if (typeof process !== "undefined" && process.versions && process.versions.node) {
            throw err;
        }
    }
}

export default init;

export function edit(input, path, value, opts) {
    checkInit();
    if (typeof input !== "string") {
        throw new Error("Invalid parameter: input must be a string");
    }
    if (typeof path !== "string") {
        throw new Error("Invalid parameter: path must be a string");
    }
    return original_edit(input, path, value, opts);
}

export function parse(input) {
    checkInit();
    if (typeof input !== "string") {
        throw new Error("Invalid parameter: input must be a string");
    }
    return original_parse(input);
}

export function stringify(input, opts) {
    checkInit();
    return original_stringify(input, opts);
}
