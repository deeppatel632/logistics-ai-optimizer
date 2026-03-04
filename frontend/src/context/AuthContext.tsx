"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import Cookies from "js-cookie";
import { authService, LoginPayload } from "@/services/api";
import { useRouter } from "next/navigation";

interface User {
  id: string;
  email: string;
  tenant_id: string;
  roles: string[];
}

interface AuthContextValue {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function parseJwt(token: string): User | null {
  try {
    const base64Url = token.split(".")[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    const payload = JSON.parse(jsonPayload);
    return {
      id: payload.sub,
      email: payload.email || "",
      tenant_id: payload.tenant_id || "",
      roles: payload.roles || [],
    };
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  // Restore session from cookie on mount
  useEffect(() => {
    const storedToken = Cookies.get("access_token");
    if (storedToken) {
      const parsed = parseJwt(storedToken);
      if (parsed) {
        setToken(storedToken);
        setUser(parsed);
      } else {
        Cookies.remove("access_token");
      }
    }
    setIsLoading(false);
  }, []);

  const login = useCallback(
    async (payload: LoginPayload) => {
      const response = await authService.login(payload);
      const { access_token, expires_in } = response.data;

      Cookies.set("access_token", access_token, {
        expires: expires_in / 86400,
        secure: process.env.NODE_ENV === "production",
        sameSite: "strict",
      });

      const parsed = parseJwt(access_token);
      setToken(access_token);
      setUser(parsed);
      router.push("/dashboard");
    },
    [router]
  );

  const logout = useCallback(() => {
    Cookies.remove("access_token");
    setToken(null);
    setUser(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        login,
        logout,
        isAuthenticated: !!token && !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
