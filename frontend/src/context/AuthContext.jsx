<<<<<<< HEAD
/* oxlint-disable react/only-export-components */
import React, { createContext, useContext, useState, useEffect } from 'react';
=======
import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
>>>>>>> c371a97313312aa71e8b6e2fcb72737f7bb284d9
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
export default AuthContext;

export function AuthProvider({ children }) {
  // Initialise from localStorage so page refresh keeps the user logged in.
  const [currentUser, setCurrentUser] = useState(() => {
    const saved = localStorage.getItem(USER_KEY);
    return saved ? JSON.parse(saved) : null;
  });

<<<<<<< HEAD
  const [currentUser, setCurrentUser] = useState(() => {
    const authFlag = localStorage.getItem('splitmate_is_authenticated');
    if (authFlag === 'false') return null;
    const saved = localStorage.getItem('splitmate_auth_user');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        const match = MOCK_USERS.find((u) => u.id === parsed.id);
        if (match) {
          return { ...match, ...parsed, name: match.name, role: match.role };
        }
        return parsed;
      } catch {
        return MOCK_USERS[0];
      }
    }
    return MOCK_USERS[0];
  });
=======
  // true when a valid JWT is in localStorage (even before /me is verified)
  const [isAuthenticated, setIsAuthenticated] = useState(
    () => Boolean(localStorage.getItem(TOKEN_KEY))
  );
>>>>>>> c371a97313312aa71e8b6e2fcb72737f7bb284d9
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

<<<<<<< HEAD
  const login = async (email, password) => {
    setIsLoading(true);
    try {
      if (!email?.trim() || !password?.trim()) {
        throw new Error('Please provide both email and password.');
      }

      const response = await apiClient.request(API_ENDPOINTS.AUTH.LOGIN, {
        method: 'POST',
        body: JSON.stringify({ email: email.trim(), password: password.trim() }),
      });

      // Preserve JWT token returned by Tanishq's backend
      if (response && response.access_token) {
        apiClient.setToken(response.access_token);
      }

      const matchedMock = MOCK_USERS.find((u) => u.email.toLowerCase() === email.trim().toLowerCase());
      const user = response?.user ? {
        id: response.user.id,
        name: response.user.name,
        email: response.user.email,
        avatar: matchedMock?.avatar || 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150',
        paypalEmail: matchedMock?.paypalEmail || `${response.user.email.split('@')[0]}@sandbox.paypal.com`,
        role: matchedMock?.role || 'Team Member',
      } : (matchedMock || {
        id: `usr_${Date.now()}`,
        name: email.split('@')[0],
        email: email.trim(),
        avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150',
        paypalEmail: `${email.split('@')[0]}-sandbox@paypal.com`,
        role: 'Team Member',
      });

      setCurrentUser(user);
      setIsAuthenticated(true);
      localStorage.setItem('splitmate_auth_user', JSON.stringify(user));
      localStorage.setItem('splitmate_is_authenticated', 'true');
      return { success: true, user };
    } catch (err) {
      return { success: false, error: err.message || 'Login failed. Please check your credentials.' };
    } finally {
      setIsLoading(false);
    }
  };

  const register = async (userData) => {
    setIsLoading(true);
    try {
      if (!userData?.name?.trim() || !userData?.email?.trim() || !userData?.password?.trim()) {
        throw new Error('Name, email, and password are required.');
      }
      if (userData.password.length < 8) {
        throw new Error('Password must be at least 8 characters.');
      }

      const response = await apiClient.request(API_ENDPOINTS.AUTH.REGISTER, {
        method: 'POST',
        body: JSON.stringify(userData),
      });

      // Preserve JWT token returned by Tanishq's backend
      if (response && response.access_token) {
        apiClient.setToken(response.access_token);
      }

      const newUser = response?.user ? {
        id: response.user.id,
        name: response.user.name,
        email: response.user.email,
        avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150',
        paypalEmail: userData.paypalEmail?.trim() || `${response.user.email.split('@')[0]}@sandbox.paypal.com`,
        role: 'Team Member',
      } : {
        id: `usr_${Date.now()}`,
        name: userData.name.trim(),
        email: userData.email.trim(),
        avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150',
        paypalEmail: userData.paypalEmail?.trim() || `${userData.email.split('@')[0]}@sandbox.paypal.com`,
        role: 'Team Member',
      };

      setCurrentUser(newUser);
      setIsAuthenticated(true);
      localStorage.setItem('splitmate_auth_user', JSON.stringify(newUser));
      localStorage.setItem('splitmate_is_authenticated', 'true');
      return { success: true, user: newUser };
    } catch (err) {
      return { success: false, error: err.message || 'Registration failed.' };
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    apiClient.clearToken();
    setCurrentUser(null);
    setIsAuthenticated(false);
    localStorage.removeItem('splitmate_auth_user');
    localStorage.setItem('splitmate_is_authenticated', 'false');
  };

  // Handle unauthorized session expiry events AFTER logout is defined
  useEffect(() => {
    const handleUnauthorized = () => logout();
    window.addEventListener('splitmate_auth_unauthorized', handleUnauthorized);
    return () => window.removeEventListener('splitmate_auth_unauthorized', handleUnauthorized);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const updateProfile = (updates) => {
    setCurrentUser((prev) => ({ ...prev, ...updates }));
  };

=======
>>>>>>> c371a97313312aa71e8b6e2fcb72737f7bb284d9
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
