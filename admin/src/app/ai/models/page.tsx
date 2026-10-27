'use client';

/**
 * AI Model Management Page (Phase 5 Day 5)
 *
 * Features:
 * - Register new ONNX/PyTorch model (file upload)
 * - List models with status badges
 * - Activate/deactivate models
 * - View model details (version, modality, confidence)
 * - Delete (soft-delete) models
 * - Redis-cached model list with 300s TTL
 */

import { useState, useEffect } from 'react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';


interface AIModel {
  id: string;
  name: string;
  version: string;
  modality: string;
  description?: string;
  gpu_required: boolean;
  status: 'active' | 'inactive' | 'deleted';
  created_at: string;
  updated_at: string;
  created_by: string;
}

export default function AIModelsPage() {
  const [models, setModels] = useState<AIModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRegistering, setIsRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    name: '',
    version: '',
    modality: 'CT',
    description: '',
    gpu_required: false,
  });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  // Fetch models on mount
  useEffect(() => {
    fetchModels();
  }, []);

  const fetchModels = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch('/pacs-api/api/v1/ai/models', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('pacs_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch models: ${response.statusText}`);
      }

      const data = await response.json();
      setModels(data.models || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const handleRegisterModel = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!selectedFile) {
      setRegisterError('Please select a model file');
      return;
    }

    try {
      setIsRegistering(true);
      setRegisterError(null);

      const formDataObj = new FormData();
      formDataObj.append('name', formData.name);
      formDataObj.append('version', formData.version);
      formDataObj.append('modality', formData.modality);
      formDataObj.append('description', formData.description);
      formDataObj.append('gpu_required', String(formData.gpu_required));
      formDataObj.append('file', selectedFile);

      const response = await fetch('/pacs-api/api/v1/ai/models', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('pacs_token')}`,
        },
        body: formDataObj,
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error?.message || 'Failed to register model');
      }

      // Refresh models list
      await fetchModels();

      // Reset form
      setFormData({
        name: '',
        version: '',
        modality: 'CT',
        description: '',
        gpu_required: false,
      });
      setSelectedFile(null);
    } catch (err) {
      setRegisterError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsRegistering(false);
    }
  };

  const handleActivateModel = async (modelId: string) => {
    try {
      const response = await fetch(`/pacs-api/api/v1/ai/models/${modelId}`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('pacs_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ status: 'active' }),
      });

      if (!response.ok) {
        throw new Error('Failed to activate model');
      }

      await fetchModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleDeactivateModel = async (modelId: string) => {
    try {
      const response = await fetch(`/pacs-api/api/v1/ai/models/${modelId}`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('pacs_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ status: 'inactive' }),
      });

      if (!response.ok) {
        throw new Error('Failed to deactivate model');
      }

      await fetchModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const handleDeleteModel = async (modelId: string) => {
    if (!confirm('Are you sure you want to delete this model?')) {
      return;
    }

    try {
      const response = await fetch(`/pacs-api/api/v1/ai/models/${modelId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('pacs_token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to delete model');
      }

      await fetchModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    }
  };

  const getStatusBadgeColor = (status: string) => {
    switch (status) {
      case 'active':
        return 'bg-green-100 text-green-800';
      case 'inactive':
        return 'bg-yellow-100 text-yellow-800';
      case 'deleted':
        return 'bg-gray-100 text-gray-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold">AI Models</h1>
          <p className="text-gray-600">Register and manage AI inference models</p>
        </div>

        <Dialog>
          <DialogTrigger asChild>
            <Button>
              📤
              Register Model
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Register AI Model</DialogTitle>
              <DialogDescription>
                Upload an ONNX or PyTorch model for inference
              </DialogDescription>
            </DialogHeader>

            <form onSubmit={handleRegisterModel} className="space-y-4">
              {registerError && (
                <Alert variant="destructive">
                  <AlertDescription>{registerError}</AlertDescription>
                </Alert>
              )}

              <div>
                <Label htmlFor="name">Model Name</Label>
                <Input
                  id="name"
                  placeholder="e.g., lung-cancer-detector"
                  value={formData.name}
                  onChange={(e) =>
                    setFormData({ ...formData, name: e.target.value })
                  }
                  required
                />
              </div>

              <div>
                <Label htmlFor="version">Version</Label>
                <Input
                  id="version"
                  placeholder="e.g., 1.0.0"
                  value={formData.version}
                  onChange={(e) =>
                    setFormData({ ...formData, version: e.target.value })
                  }
                  required
                />
              </div>

              <div>
                <Label htmlFor="modality">Modality</Label>
                <Select
                  value={formData.modality}
                  onValueChange={(value) =>
                    setFormData({ ...formData, modality: value })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="CT">CT</SelectItem>
                    <SelectItem value="MR">MR</SelectItem>
                    <SelectItem value="CR">CR</SelectItem>
                    <SelectItem value="DX">DX</SelectItem>
                    <SelectItem value="US">US</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label htmlFor="description">Description</Label>
                <Input
                  id="description"
                  placeholder="Model description"
                  value={formData.description}
                  onChange={(e) =>
                    setFormData({ ...formData, description: e.target.value })
                  }
                />
              </div>

              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  id="gpu_required"
                  checked={formData.gpu_required}
                  onChange={(e) =>
                    setFormData({ ...formData, gpu_required: e.target.checked })
                  }
                />
                <Label htmlFor="gpu_required">GPU Required</Label>
              </div>

              <div>
                <Label htmlFor="file">Model File (.onnx)</Label>
                <Input
                  id="file"
                  type="file"
                  accept=".onnx,.pt,.pth"
                  onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                  required
                />
              </div>

              <Button
                type="submit"
                disabled={isRegistering}
                className="w-full"
              >
                {isRegistering ? (
                  <>
                    ⏳
                    Registering...
                  </>
                ) : (
                  'Register Model'
                )}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Models ({models.length})</CardTitle>
          <CardDescription>
            Registered AI models with cache TTL: 300s
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              ⏳
            </div>
          ) : models.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              No models registered yet
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Version</TableHead>
                    <TableHead>Modality</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>GPU</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {models.map((model) => (
                    <TableRow key={model.id}>
                      <TableCell className="font-medium">{model.name}</TableCell>
                      <TableCell>{model.version}</TableCell>
                      <TableCell>{model.modality}</TableCell>
                      <TableCell>
                        <Badge className={getStatusBadgeColor(model.status)}>
                          {model.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {model.gpu_required ? '✅' : '❌'}
                      </TableCell>
                      <TableCell className="text-sm text-gray-600">
                        {new Date(model.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-2">
                          {model.status === 'inactive' && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleActivateModel(model.id)}
                            >
                              ⚙️
                            </Button>
                          )}
                          {model.status === 'active' && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleDeactivateModel(model.id)}
                            >
                              Deactivate
                            </Button>
                          )}
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => handleDeleteModel(model.id)}
                          >
                            🗑️
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
