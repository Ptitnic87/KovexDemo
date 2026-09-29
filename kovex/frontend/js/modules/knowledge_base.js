/**
 * PyGIA Frontend - Knowledge Base Module
 * Interface JavaScript pour communiquer avec la KB
 */

const KnowledgeBase = {
    /**
     * Récupère les statistiques de la KB
     */
    async getStats() {
        try {
            return await API.get('/kb/stats');
        } catch (error) {
            return null;
        }
    },
    
    // ========== DROITS SOCLES ==========
    
    /**
     * Récupère les droits socles détectés
     * @returns {Promise<string[]>} Liste des droits socles
     */
    async getBirthRights() {
        try {
            return await API.get('/kb/birth-rights');
        } catch (error) {
            return [];
        }
    },
    
    /**
     * Récupère les infos complètes sur les droits socles
     * @returns {Promise<Object>} Infos (threshold, detected_at, rights, count)
     */
    async getBirthRightsInfo() {
        try {
            return await API.get('/kb/birth-rights/info');
        } catch (error) {
            return null;
        }
    },
    
    /**
     * Enregistre les droits socles détectés
     * @param {string[]} rights - Liste des droits socles
     * @param {number} threshold - Seuil utilisé
     */
    async setBirthRights(rights, threshold = 90.0) {
        try {
            return await API.post('/kb/birth-rights', { rights, threshold });
        } catch (error) {
            throw error;
        }
    },
    
    /**
     * Efface les droits socles (pour relancer détection)
     */
    async clearBirthRights() {
        try {
            return await API.delete('/kb/birth-rights');
        } catch (error) {
            throw error;
        }
    },
    
    // ========== VALIDATED ROLES ==========
    
    /**
     * Récupère les rôles validés
     * @param {string|null} roleType - 'APPLICATIF', 'METIER', ou null pour tous
     * @returns {Promise<Object[]>} Liste des rôles validés
     */
    async getValidatedRoles(roleType = null) {
        try {
            const params = roleType ? { role_type: roleType } : {};
            const response = await API.get('/kb/validated-roles', params);
            return response.roles || [];
        } catch (error) {
            return [];
        }
    },
    
    /**
     * Récupère un rôle validé par son ID
     * @param {string} roleId - ID du rôle
     * @returns {Promise<Object|null>} Rôle ou null si introuvable
     */
    async getRoleById(roleId) {
        try {
            return await API.get(`/kb/validated-roles/${roleId}`);
        } catch (error) {
            // Le client d'API rend une `APIError`, qui porte `status` — pas
            // `response.status`. La condition testait donc une propriété qui
            // n'existe pas : un rôle absent remontait en erreur au lieu de
            // rendre `null`, contrairement à ce que la fonction annonce.
            if (error.status === 404) {
                return null;
            }
            throw error;
        }
    },
    
    /**
     * Valide et enregistre un rôle dans la KB
     * @param {Object} roleData - Données du rôle à valider
     */
    async validateRole(roleData) {
        try {
            return await API.post('/kb/validate-role', roleData);
        } catch (error) {
            throw error;
        }
    },
    
    /**
     * Met à jour un rôle validé existant
     * @param {string} roleId - ID du rôle
     * @param {Object} updates - Champs à mettre à jour
     */
    async updateValidatedRole(roleId, updates) {
        try {
            return await API.put(`/kb/validated-roles/${roleId}`, updates);
        } catch (error) {
            throw error;
        }
    },
    
    /**
     * Supprime un rôle validé
     * @param {string} roleId - ID du rôle à supprimer
     */
    async deleteValidatedRole(roleId) {
        try {
            return await API.delete(`/kb/validated-roles/${roleId}`);
        } catch (error) {
            throw error;
        }
    },
    
    // ========== REJECTED ROLES ==========
    
    /**
     * Récupère la liste des rôles rejetés
     * @returns {Promise<string[]>} IDs des rôles rejetés
     */
    async getRejectedRoles() {
        try {
            const response = await API.get('/kb/rejected-roles');
            return response.rejected_roles || [];
        } catch (error) {
            return [];
        }
    },
    
    /**
     * Ajoute un rôle à la blacklist
     * @param {string} roleId - ID du rôle à rejeter
     * @param {string} reason - Raison du rejet
     */
    /**
     * Refuse un rôle.
     *
     * `indicateurs` n'accompagne que le refus décidé par un analyste devant
     * un candidat. L'écartement automatique du rôle d'origine, quand
     * quelqu'un en modifie un, n'en transmet pas : ce n'est pas un jugement,
     * et le compter comme tel ferait passer des rôles corrects pour rejetés
     * dans l'historique du workspace.
     */
    async rejectRole(roleId, reason = '', indicateurs = null) {
        try {
            const charge = { role_id: roleId, reason };
            if (indicateurs) charge.indicateurs = indicateurs;
            return await API.post('/kb/reject-role', charge);
        } catch (error) {
            throw error;
        }
    },
    
    /**
     * Retire un rôle de la blacklist
     * @param {string} roleId - ID du rôle à réhabiliter
     */
    async unrejectRole(roleId) {
        try {
            return await API.delete(`/kb/rejected-roles/${roleId}`);
        } catch (error) {
            throw error;
        }
    },
    
    /**
     * Vérifie si un rôle est dans la blacklist
     * @param {string} roleId - ID du rôle à vérifier
     * @returns {Promise<boolean>} True si rejeté
     */
    async isRoleRejected(roleId) {
        try {
            const response = await API.get(`/kb/rejected-roles/${roleId}/check`);
            return response.is_rejected;
        } catch (error) {
            return false;
        }
    },
    
    // ========== EXCLUDED USERS ==========
    
    /**
     * Récupère les utilisateurs exclus du mining
     * @returns {Promise<string[]>} IDs des utilisateurs exclus
     */
    async getExcludedUsers() {
        try {
            const response = await API.get('/kb/excluded-users');
            return response.excluded_users || [];
        } catch (error) {
            return [];
        }
    },
    
    /**
     * Exclut un utilisateur du mining
     * @param {string} userId - ID de l'utilisateur
     * @param {string} reason - Raison de l'exclusion
     */
    async excludeUser(userId, reason = '') {
        try {
            return await API.post('/kb/exclude-user', { user_id: userId, reason });
        } catch (error) {
            throw error;
        }
    },
    
    /**
     * Réintègre un utilisateur
     * @param {string} userId - ID de l'utilisateur
     */
    async removeExcludedUser(userId) {
        try {
            return await API.delete(`/kb/excluded-users/${userId}`);
        } catch (error) {
            throw error;
        }
    },
    
    // ========== MINING HISTORY ==========
    
    /**
     * Récupère l'historique des runs de mining
     * @param {number} limit - Nombre max de runs à retourner
     * @returns {Promise<Object[]>}
     */
    async getMiningHistory(limit = 10) {
        try {
            const response = await API.get('/kb/mining-history', { limit });
            return response.history || [];
        } catch (error) {
            return [];
        }
    },
    
    /**
     * Enregistre un run de mining
     * @param {Object} runInfo - Infos sur le run
     */
    async addMiningRun(runInfo) {
        try {
            return await API.post('/kb/mining-history', runInfo);
        } catch (error) {
            throw error;
        }
    },
    
    // ========== BACKUP & RESTORE ==========
    
    /**
     * Crée une sauvegarde de la KB
     * @returns {Promise<Object>} Infos du backup (status, path)
     */
    async createBackup() {
        try {
            return await API.post('/kb/backup');
        } catch (error) {
            throw error;
        }
    },
    
    /**
     * Restaure la KB depuis un fichier de backup
     * @param {string} backupPath - Chemin vers le backup
     * @returns {Promise<Object>} Status de la restauration
     */
    async restoreBackup(backupPath) {
        const confirme = await Confirm.demander({
            titre: I18n.t('confirm.kb_restore_title'),
            message: I18n.t('confirm.kb_restore', { sauvegarde: backupPath }),
            danger: true,
        });
        if (!confirme) return { status: 'cancelled' };
        
        try {
            return await API.post('/kb/restore', { backup_path: backupPath });
        } catch (error) {
            throw error;
        }
    },
    
    /**
     * ⚠️ DANGEREUX : Efface TOUTES les données de la KB
     * @returns {Promise<Object>} Status de l'opération
     */
    async clearAll() {
        // Deux demandes successives : effacer la base efface les décisions de
        // gouvernance du workspace, pas seulement un calcul.
        const premiere = await Confirm.demander({
            titre: I18n.t('confirm.kb_clear_title'),
            message: I18n.t('confirm.kb_clear'),
            details: [I18n.t('confirm.kb_clear_detail_roles'),
                      I18n.t('confirm.kb_clear_detail_birth'),
                      I18n.t('confirm.kb_clear_detail_perimeter')],
            danger: true,
        });
        if (!premiere) return { status: 'cancelled' };

        const seconde = await Confirm.demander({
            titre: I18n.t('confirm.kb_clear_title'),
            message: I18n.t('confirm.kb_clear_second'),
            confirmer: I18n.t('confirm.kb_clear_action'),
            danger: true,
        });
        if (!seconde) return { status: 'cancelled' };
        
        try {
            return await API.delete('/kb/clear-all?confirm=true');
        } catch (error) {
            throw error;
        }
    }
};

// Export global
window.KnowledgeBase = KnowledgeBase;