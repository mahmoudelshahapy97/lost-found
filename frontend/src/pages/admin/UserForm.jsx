import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";

import { errorMessage } from "../../api/client";
import { users as usersApi } from "../../api/endpoints";
import { ROLES } from "../../auth/roles";
import { useToast } from "../../components/Toast";

const EMPTY = { username: "", email: "", full_name: "", password: "", role: "viewer" };

/**
 * One dialog for both create and edit. `editingUser` null means "new
 * account"; a role/name change on an existing account never touches the
 * password field -- that is what the reset-password action on the list is for.
 */
export function UserForm({ open, editingUser, onClose, onSaved }) {
  const toast = useToast();
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setForm(
      editingUser
        ? {
            username: editingUser.username,
            email: editingUser.email,
            full_name: editingUser.full_name || "",
            password: "",
            role: editingUser.role,
          }
        : EMPTY
    );
  }, [open, editingUser]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (editingUser) {
        await usersApi.update(editingUser.user_id, {
          full_name: form.full_name || null,
          role: form.role,
        });
        toast.success(`Updated "${form.username}".`);
      } else {
        await usersApi.create({
          username: form.username,
          email: form.email,
          password: form.password,
          full_name: form.full_name || null,
          role: form.role,
        });
        toast.success(`Created "${form.username}".`);
      }
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = editingUser
    ? Boolean(form.role)
    : Boolean(form.username && form.email && form.password);

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{editingUser ? `Edit ${editingUser.username}` : "New account"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            label="Username"
            value={form.username}
            onChange={set("username")}
            disabled={Boolean(editingUser)}
            fullWidth
          />
          <TextField
            label="Email"
            type="email"
            value={form.email}
            onChange={set("email")}
            disabled={Boolean(editingUser)}
            fullWidth
          />
          <TextField
            label="Full name"
            value={form.full_name}
            onChange={set("full_name")}
            fullWidth
          />
          {!editingUser && (
            <TextField
              label="Password"
              type="password"
              value={form.password}
              onChange={set("password")}
              helperText="At least 8 characters, with upper, lower, a digit and a symbol."
              fullWidth
            />
          )}
          <FormControl fullWidth>
            <InputLabel id="user-role-label">Role</InputLabel>
            <Select
              labelId="user-role-label"
              label="Role"
              value={form.role}
              onChange={set("role")}
            >
              {ROLES.map((role) => (
                <MenuItem key={role} value={role}>
                  {role}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} disabled={busy} color="inherit">
          Cancel
        </Button>
        <Button onClick={handleSubmit} disabled={busy || !canSubmit} variant="contained">
          {busy ? "Saving…" : editingUser ? "Save changes" : "Create account"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default UserForm;
