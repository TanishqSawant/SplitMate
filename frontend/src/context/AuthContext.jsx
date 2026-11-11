import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { MOCK_USERS } from '../api/mockData';
import { apiClient } from '../api/client';
import { API_ENDPOINTS } from '../api/endpoints';

// ---------------------------------------------------------------------------
// Storage helpers – single source of truth for token key
// ---------------------------------------------------------------------------
const TOKEN_KEY = 'splitmate_token';
const USER_KEY = 'splitmate_auth_user';

function saveToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/**
 * Merge a backend UserResponse with optional mock-user extras (avatar, paypalEmail, role).
 * Fields from the real backend always win; mock extras fill the gaps only.
 */
function mergeWithMockExtras(backendUser) {
  const mock = MOCK_USERS.find(
    (u) => u.email.toLowerCase() === backendUser.email.toLowerCase()
  );
  return {
    // Mock extras first so real fields overwrite
    ...(mock || {
      avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150',
      paypalEmail: `${backendUser.email.split('@')[0]}-sandbox@sandbox.paypal.com`,
      role: 'Team Member',
    }),
    // Real backend fields overwrite everything
    id: backendUser.id,
    name: backendUser.name,
    email: backendUser.email,
    created_at: backendUser.created_at,
  };
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------
const AuthContext = createContext();

export function AuthProvider({ children }) {
  // Initialise from localStorage so page refresh keeps the user logged in.
  const [currentUser, setCurrentUser] = useState(() => {
    const saved = localStorage.getItem(USER_KEY);
    return saved ? JSON.parse(saved) : null;
  });

  // true when a valid JWT is in localStorage (even before /me is verified)
  const [isAuthenticated, setIsAuthenticated] = useState(
    () => Boolean(localStorage.getItem(TOKEN_KEY))
  );
  const [isLoading, setIsLoading] = useState(false);

  // Persist the user object so a page refresh doesn't blank the UI.
  useEffect(() => {
    if (currentUser) {
      localStorage.setItem(USER_KEY, JSON.stringify(currentUser));
    } else {
      localStorage.removeItem(USER_KEY);
    }
  }, [currentUser]);

  // On mount, if we have a stored token, verify it against the backend.
  // This catches expired tokens after a page refresh without forcing a re-login.
  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return;

    apiClient
      .request(API_ENDPOINTS.AUTH.CURRENT_USER)
      .then((backendUser) => {
        setCurrentUser(mergeWithMockExtras(backendUser));
        setIsAuthenticated(true);
      })
      .catch((err) => {
        // Token is expired or invalid – clear everything and show as logged out.
        const isAuthError =
          err.message.includes('401') ||
          err.message.includes('expired') ||
          err.message.includes('credentials') ||
          err.message.includes('Authentication required');
        if (isAuthError) {
          console.warn('[SplitMate Auth] Stored token is invalid or expired – logging out.', err.message);
          clearToken();
          setCurrentUser(null);
          setIsAuthenticated(false);
        }
        // If the backend is simply offline, leave the cached user in place
        // so the app still loads in mock-fallback mode.
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // -------------------------------------------------------------------------
  // login
  // -------------------------------------------------------------------------
  const login = async (email, password) => {
    setIsLoading(true);
    try {
      const result = await apiClient.request(API_ENDPOINTS.AUTH.LOGIN, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });

      // result = { access_token, token_type, user: { id, name, email, created_at } }
      saveToken(result.access_token);
      const user = mergeWithMockExtras(result.user);
      setCurrentUser(user);
      setIsAuthenticated(true);
      return { success: true, user };
    } catch (err) {
      return { success: false, error: err.message };
    } finally {
      setIsLoading(false);
    }
  };

  // -------------------------------------------------------------------------
  // register
  // -------------------------------------------------------------------------
  const register = async (userData) => {
    setIsLoading(true);
    try {
      const result = await apiClient.request(API_ENDPOINTS.AUTH.REGISTER, {
        method: 'POST',
        body: JSON.stringify({
          name: userData.name,
          email: userData.email,
          password: userData.password,
        }),
      });

      // result = { access_token, token_type, user: { id, name, email, created_at } }
      saveToken(result.access_token);
      const user = mergeWithMockExtras(result.user);
      setCurrentUser(user);
      setIsAuthenticated(true);
      return { success: true, user };
    } catch (err) {
      return { success: false, error: err.message };
    } finally {
      setIsLoading(false);
    }
  };

  // -------------------------------------------------------------------------
  // logout
  // -------------------------------------------------------------------------
  const logout = useCallback(() => {
    clearToken();
    setCurrentUser(null);
    setIsAuthenticated(false);
  }, []);

  // -------------------------------------------------------------------------
  // updateProfile  (local only – no backend profile endpoint exists yet)
  // -------------------------------------------------------------------------
  const updateProfile = (updates) => {
    setCurrentUser((prev) => ({ ...prev, ...updates }));
  };

  // -------------------------------------------------------------------------
  // switchUser  (hackathon demo quick-switch – preserved intentionally)
  // -------------------------------------------------------------------------
  const switchUser = (userId) => {
    const found = MOCK_USERS.find((u) => u.id === userId);
    if (found) {
      setCurrentUser(found);
      setIsAuthenticated(true);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        isAuthenticated,
        isLoading,
        // allUsers stays as MOCK_USERS so member-lookup UI continues to work
        allUsers: MOCK_USERS,
        switchUser,
        login,
        register,
        logout,
        updateProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
