import React, { createContext, useContext, useState, useEffect } from 'react';
import { MOCK_USERS } from '../api/mockData';
import { apiClient } from '../api/client';
import { API_ENDPOINTS } from '../api/endpoints';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  // Only restore user from localStorage when a real JWT token also exists.
  // Without a token the user is unauthenticated regardless of any saved profile.
  const [currentUser, setCurrentUser] = useState(() => {
    const token = localStorage.getItem('splitmate_token');
    if (!token) return null;
    const saved = localStorage.getItem('splitmate_auth_user');
    return saved ? JSON.parse(saved) : null;
  });
  const [token, setToken] = useState(() => {
    return localStorage.getItem('splitmate_token') || null;
  });
  // Authenticated only when a real JWT token is present in localStorage.
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return Boolean(localStorage.getItem('splitmate_token'));
  });
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (currentUser) {
      localStorage.setItem('splitmate_auth_user', JSON.stringify(currentUser));
    } else {
      localStorage.removeItem('splitmate_auth_user');
    }
  }, [currentUser]);

  useEffect(() => {
    if (token) {
      localStorage.setItem('splitmate_token', token);
      apiClient.setAuthToken(token);
    } else {
      localStorage.removeItem('splitmate_token');
      apiClient.setAuthToken(null);
    }
  }, [token]);

  // Demo user quick-switch – only allowed when a real JWT token already exists.
  // Without a real token this would create a false "authenticated" state.
  const switchUser = (userId) => {
    if (!token) return; // Guard: never switch to a mock user without a real session
    const found = MOCK_USERS.find((u) => u.id === userId);
    if (found) {
      setCurrentUser(found);
    }
  };

  const login = async (email, password) => {
    setIsLoading(true);
    try {
      const result = await apiClient.request(API_ENDPOINTS.AUTH.LOGIN, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });

      if (result.access_token) {
        setToken(result.access_token);
        localStorage.setItem('splitmate_token', result.access_token);
        apiClient.setAuthToken(result.access_token);
      }

      const user = result.user || MOCK_USERS.find((u) => u.email === email) || {
        id: `usr_${Date.now()}`,
        name: email.split('@')[0],
        email,
        avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150',
        paypalEmail: `${email.split('@')[0]}-sandbox@paypal.com`,
        role: 'Team Member',
      };
      setCurrentUser(user);
      setIsAuthenticated(true);
      return { success: true, user, token: result.access_token };
    } catch (err) {
      return { success: false, error: err.message };
    } finally {
      setIsLoading(false);
    }
  };

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

      if (result.access_token) {
        setToken(result.access_token);
        localStorage.setItem('splitmate_token', result.access_token);
        apiClient.setAuthToken(result.access_token);
      }

      const user = result.user || {
        id: `usr_${Date.now()}`,
        name: userData.name,
        email: userData.email,
        avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150',
        paypalEmail: userData.paypalEmail || `${userData.email.split('@')[0]}@sandbox.paypal.com`,
        role: 'Team Member',
      };
      setCurrentUser(user);
      setIsAuthenticated(true);
      return { success: true, user, token: result.access_token };
    } catch (err) {
      return { success: false, error: err.message };
    } finally {
      setIsLoading(false);
    }
  };

  const logout = () => {
    setCurrentUser(null);
    setToken(null);
    localStorage.removeItem('splitmate_auth_user');
    localStorage.removeItem('splitmate_token');
    apiClient.setAuthToken(null);
    setIsAuthenticated(false);
  };

  const updateProfile = (updates) => {
    setCurrentUser((prev) => ({ ...prev, ...updates }));
  };

  return (
    <AuthContext.Provider
      value={{
        currentUser,
        token,
        isAuthenticated,
        isLoading,
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

