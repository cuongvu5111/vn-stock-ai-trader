// Ngày tạo: 2026-11-17
// Mục đích: Ma trận quyền phía UI (pure functions) phản chiếu RBAC của backend.
// Lý do: Chỉ để ẩn/disable nút cho hợp lý; backend (`require_viewer/trader/admin`) vẫn là nơi quyết định cuối cùng.

import { UserRole } from './auth.models';

export interface Capabilities {
  canOperate: boolean;
  canActivateKillSwitch: boolean;
  canDeactivateKillSwitch: boolean;
  canEditRiskConfig: boolean;
  canSyncRealData: boolean;
  canCreateStock: boolean;
  canManageUsers: boolean;
}

export function capabilitiesFor(role: UserRole | null | undefined): Capabilities {
  const isAdmin = role === 'admin';
  const isTrader = role === 'trader';
  const operator = isAdmin || isTrader;
  return {
    canOperate: operator,
    canActivateKillSwitch: operator,
    canDeactivateKillSwitch: isAdmin,
    canEditRiskConfig: isAdmin,
    canSyncRealData: isAdmin,
    canCreateStock: isAdmin,
    canManageUsers: isAdmin,
  };
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: 'Admin — quản trị toàn quyền',
  trader: 'Trader — thao tác nghiệp vụ',
  viewer: 'Viewer — chỉ xem',
};
