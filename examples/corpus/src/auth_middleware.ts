import { verify, JwtPayload } from "jsonwebtoken";
import type { Request, Response, NextFunction } from "express";

const AUDIENCE = "notes-api";

export interface AuthenticatedRequest extends Request {
  user?: JwtPayload & { sub: string; roles: string[] };
}

/**
 * Express middleware that validates the JWT bearer token on every request.
 * Rejects missing or malformed headers with 401, and expired tokens with
 * 401 + error code "token_expired" so the client knows to refresh.
 */
export function authMiddleware(publicKey: string) {
  return (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    const header = req.headers.authorization;
    if (!header || !header.startsWith("Bearer ")) {
      return res.status(401).json({ error: "missing_token" });
    }
    try {
      const claims = verify(header.slice(7), publicKey, {
        algorithms: ["RS256"],
        audience: AUDIENCE,
      }) as AuthenticatedRequest["user"];
      req.user = claims;
      return next();
    } catch (err: any) {
      const code = err?.name === "TokenExpiredError" ? "token_expired" : "invalid_token";
      return res.status(401).json({ error: code });
    }
  };
}

/** Allow the request only if the authenticated user has one of the given roles. */
export const requireRole = (...roles: string[]) =>
  (req: AuthenticatedRequest, res: Response, next: NextFunction) => {
    const userRoles = req.user?.roles ?? [];
    if (!roles.some((r) => userRoles.includes(r))) {
      return res.status(403).json({ error: "forbidden" });
    }
    return next();
  };
