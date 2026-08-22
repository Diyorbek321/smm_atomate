/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin. Empty (default) means same-origin via the Express proxy. */
  readonly VITE_API_URL?: string;
  /** Only needed when calling the backend directly instead of via the proxy. */
  readonly VITE_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
