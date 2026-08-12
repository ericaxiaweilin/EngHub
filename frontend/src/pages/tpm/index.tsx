import React from 'react';
import { Routes, Route } from 'react-router-dom';
import OfficeTPM from './OfficeTPM';
import EarlyEquipmentManagement from './EarlyEquipmentManagement';
import TrainingEducation from './TrainingEducation';
import FocusedImprovement from './FocusedImprovement';
import SafetyEnvironment from './SafetyEnvironment';

const TPMModule: React.FC = () => {
  return (
    <Routes>
      <Route path="/" element={<OfficeTPM />} />
      <Route path="/office" element={<OfficeTPM />} />
      <Route path="/early-equipment" element={<EarlyEquipmentManagement />} />
      <Route path="/training" element={<TrainingEducation />} />
      <Route path="/kaizen" element={<FocusedImprovement />} />
      <Route path="/safety" element={<SafetyEnvironment />} />
    </Routes>
  );
};

export default TPMModule;
