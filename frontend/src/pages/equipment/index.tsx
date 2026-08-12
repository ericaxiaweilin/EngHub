import React from 'react';
import { Routes, Route } from 'react-router-dom';
import TPMDashboard from './TPMDashboard';
import EquipmentCenter from './EquipmentCenter';
import MaintenanceCenter from './MaintenanceCenter';
import OeeDashboard from './OeeDashboard';

const EquipmentModule: React.FC = () => {
  return (
    <Routes>
      <Route path="/" element={<TPMDashboard />} />
      <Route path="/equipment" element={<EquipmentCenter />} />
      <Route path="/maintenance" element={<MaintenanceCenter />} />
      <Route path="/oee" element={<OeeDashboard />} />
    </Routes>
  );
};

export default EquipmentModule;
