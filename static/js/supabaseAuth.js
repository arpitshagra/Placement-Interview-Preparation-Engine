/**
 * static/js/supabaseAuth.js
 * =========================
 * Frontend Supabase Authentication helper for IntervIQ.
 * Initializes the Supabase client using public config fetched from /api/config.
 * Handles Google OAuth sign-in, session synchronization, and sign-out.
 */

(function () {
  let supabaseClientPromise = null;

  /**
   * Initializes and returns the Supabase client instance.
   * Caches the client promise to prevent redundant config fetches.
   */
  window.getSupabaseClient = function () {
    if (supabaseClientPromise) {
      return supabaseClientPromise;
    }

    supabaseClientPromise = (async function () {
      if (window.supabaseClient) {
        return window.supabaseClient;
      }

      if (typeof supabase === "undefined" || !supabase.createClient) {
        console.error("[SupabaseAuth] @supabase/supabase-js library is not loaded.");
        throw new Error("Supabase library not loaded.");
      }

      try {
        const resp = await fetch("/api/config");
        if (!resp.ok) {
          throw new Error(`Failed to fetch /api/config: ${resp.status}`);
        }
        const cfg = await resp.json();
        if (!cfg.supabase_url || !cfg.supabase_anon_key) {
          throw new Error("Missing supabase_url or supabase_anon_key in config.");
        }

        window.supabaseClient = supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key, {
          auth: {
            persistSession: true,
            autoRefreshToken: true,
            detectSessionInUrl: true,
          },
        });

        // Listen for auth state changes and sync backend session if needed
        window.supabaseClient.auth.onAuthStateChange(async (event, session) => {
          if (event === "SIGNED_IN" && session?.access_token) {
            console.log("[SupabaseAuth] SIGNED_IN event received.");
            try {
              await syncServerSession(session.access_token);
            } catch (err) {
              console.warn("[SupabaseAuth] Session sync warning:", err);
            }
          } else if (event === "SIGNED_OUT") {
            console.log("[SupabaseAuth] SIGNED_OUT event received.");
          }
        });

        return window.supabaseClient;
      } catch (err) {
        console.error("[SupabaseAuth] Initialization error:", err);
        supabaseClientPromise = null; // allow retry
        throw err;
      }
    })();

    return supabaseClientPromise;
  };

  /**
   * Synchronizes the client-side Supabase token with Flask's session.
   * @param {string} accessToken
   * @returns {Promise<Object>} Backend response
   */
  window.syncServerSession = async function (accessToken) {
    const res = await fetch("/api/auth/session", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ access_token: accessToken }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `Server session sync failed (${res.status})`);
    }

    return await res.json();
  };

  /**
   * Initiates Google OAuth sign-in flow via Supabase.
   */
  window.signInWithGoogle = async function (btnElement) {
    let originalHtml = "";
    if (btnElement) {
      originalHtml = btnElement.innerHTML;
      btnElement.disabled = true;
      btnElement.innerHTML = `
        <svg class="spinner" viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" style="animation: spin 1s linear infinite; margin-right: 8px;">
          <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
          <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round"></path>
        </svg>
        Connecting to Google...
      `;
    }

    try {
      const client = await window.getSupabaseClient();
      const callbackUrl = `${window.location.origin}/auth/callback`;

      const { data, error } = await client.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: callbackUrl,
          queryParams: {
            access_type: "offline",
            prompt: "consent",
          },
        },
      });

      if (error) {
        throw error;
      }

      // If signInWithOAuth returns a direct URL to redirect to
      if (data?.url) {
        window.location.href = data.url;
      }
    } catch (err) {
      console.error("[SupabaseAuth] Google sign-in error:", err);
      alert(`Google Sign-In Error: ${err.message || err}`);
      if (btnElement) {
        btnElement.disabled = false;
        btnElement.innerHTML = originalHtml;
      }
    }
  };

  /**
   * Handles user sign-out from both client Supabase and server Flask session.
   */
  window.handleSupabaseLogout = async function (event) {
    if (event && event.preventDefault) {
      event.preventDefault();
    }

    try {
      if (window.supabaseClient) {
        await window.supabaseClient.auth.signOut();
      } else {
        const client = await window.getSupabaseClient().catch(() => null);
        if (client) {
          await client.auth.signOut().catch(() => {});
        }
      }
    } catch (e) {
      console.warn("[SupabaseAuth] Sign out client notice:", e);
    }

    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch (e) {
      console.warn("[SupabaseAuth] Sign out server notice:", e);
    }

    window.location.href = "/login";
  };

  // Eagerly initialize Supabase client in the background if possible
  document.addEventListener("DOMContentLoaded", () => {
    if (typeof supabase !== "undefined") {
      window.getSupabaseClient().catch((err) => {
        // Log quietly; pages that don't need auth can ignore
        console.debug("[SupabaseAuth] Background init note:", err.message);
      });
    }
  });
})();
