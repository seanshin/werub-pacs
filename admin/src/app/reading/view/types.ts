export type Report = {
  id: string; status: string; findings: string; impression: string;
  recommendation: string; urgency: string; author_name: string;
  signed_at: string | null; signed_by_name: string | null;
};

export type Template = {
  id: string; name: string; modality: string;
  sections: { name: string; key: string; default?: string }[];
  normal_template: string | null; impression_template: string | null;
  macros: Record<string, string> | null;
};

export type StudyInfo = {
  patient_name: string; patient_id: string; modality: string;
  study_description: string; study_date: string; accession_number: string;
  series_count: number; sla_minutes: number | null; sla_level: string | null;
};
