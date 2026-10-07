/** True in the read-only demo build, which reads a JSON snapshot instead of calling the API. */
export const IS_STATIC = process.env.NEXT_PUBLIC_STATIC_DATA === "1";

/** Path prefix the app is served under ("" at a domain root). */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export const REPO_URL = "https://github.com/laminedo/lottery-timesfm";
